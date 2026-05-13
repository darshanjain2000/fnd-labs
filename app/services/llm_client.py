"""OpenRouter client with JSON response + daily spend cap."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx

from app.config import get_settings
from app.core.logging import get_logger
from app.exceptions.domain import SpendCapExceededException

log = get_logger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_COSTS = {
    "anthropic/claude-3.5-sonnet": (3.0, 15.0),
    "openai/gpt-4o-mini": (0.15, 0.60),
}


# Back-compat alias — existing code imports SpendCapExceeded from this module.
# New code should import SpendCapExceededException from app.exceptions directly.
SpendCapExceeded = SpendCapExceededException


class LLMClient:
    def __init__(self) -> None:
        self.s = get_settings()
        self._spend_usd = 0.0
        self._spend_day: date = date.today()

    def _reset_if_new_day(self) -> None:
        today = date.today()
        if today != self._spend_day:
            log.info("llm_daily_reset", prev_usd=self._spend_usd)
            self._spend_usd = 0.0
            self._spend_day = today

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        inp, out = _COSTS.get(self.s.openrouter_model, (5.0, 15.0))
        return (prompt_tokens * inp + completion_tokens * out) / 1_000_000

    def chat_json(
        self, system: str, user: str, schema_hint: str = ""
    ) -> dict[str, Any]:
        """Synchronous call, returns parsed JSON dict or {} on failure/unavailable."""
        self._reset_if_new_day()
        if self._spend_usd >= self.s.openrouter_daily_usd_cap:
            raise SpendCapExceeded(f"daily cap ${self.s.openrouter_daily_usd_cap} hit")
        if not self.s.openrouter_api_key:
            log.warning("llm_no_api_key_degrade")
            return {}

        sys_prompt = system + (
            ("\n\nRespond ONLY with JSON. " + schema_hint) if schema_hint else ""
        )
        payload = {
            "model": self.s.openrouter_model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.s.openrouter_api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(OPENROUTER_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            # Broad catch: httpx raises several unrelated exception types
            # (TimeoutException, ConnectError, HTTPStatusError, RemoteProtocolError).
            # Any LLM failure degrades silently to the fallback rule — never crashes
            # the pipeline.
            log.error("llm_call_failed", error=str(e))
            return {}

        usage = data.get("usage", {})
        self._spend_usd += self._estimate_cost(
            usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        )
        log.info("llm_call_ok", spend_usd=round(self._spend_usd, 4))

        try:
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, json.JSONDecodeError) as e:
            log.warning("llm_parse_failed", error=str(e))
            return {}
