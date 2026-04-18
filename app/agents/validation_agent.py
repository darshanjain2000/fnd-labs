from __future__ import annotations

from dataclasses import dataclass

from config import get_settings
from core.logging import get_logger
from services.llm_client import LLMClient, SpendCapExceeded
from strategies.base import Signal

log = get_logger(__name__)

_PRESETS = {
    "conservative": (
        "You are an ultra-conservative F&O validator. Reject anything ambiguous. "
        "Approve only on textbook setups with strong confirmation."
    ),
    "balanced": (
        "You are a risk-aware F&O validator. Approve strong setups, reject weak ones. "
        "You cannot override risk rules; only approve or reject."
    ),
    "aggressive": (
        "You are an opportunistic F&O validator. Approve reasonable setups readily, "
        "but always reject on conflicting signals or extreme volatility."
    ),
}

SCHEMA_HINT = (
    'Schema: {"approve": bool, "confidence": number 0..1, '
    '"reasoning": string (<= 200 chars), "adjusted_stop": number or null}'
)


@dataclass
class Validation:
    approved: bool
    confidence: float
    reasoning: str
    adjusted_stop: float | None = None
    source: str = "llm"  # "llm" | "disabled" | "fallback" | "spend_cap"


class ValidationAgent:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def _fallback(self, sig: Signal, tag: str) -> Validation:
        s = get_settings()
        approved = sig.confidence >= s.ai_fallback_approve_threshold
        return Validation(approved, sig.confidence, tag, source=tag)

    def validate(self, signal: Signal, rag_context: list[str] | None = None) -> Validation:
        s = get_settings()

        if not s.openrouter_enabled:
            return self._fallback(signal, "disabled")

        rag_block = ""
        if rag_context:
            rag_block = "\n\nSimilar past trades:\n- " + "\n- ".join(rag_context[:5])

        user = (
            f"Symbol: {signal.symbol}\n"
            f"Strategy: {signal.strategy}\n"
            f"Side: {signal.side}\n"
            f"Entry: {signal.entry}\n"
            f"Stop: {signal.stop_loss}\n"
            f"Target: {signal.target}\n"
            f"Strategy confidence: {signal.confidence:.2f}\n"
            f"Indicators: {signal.context}"
            f"{rag_block}"
        )
        system = _PRESETS.get(s.agent_preset, _PRESETS["balanced"])

        try:
            result = self.llm.chat_json(system, user, SCHEMA_HINT)
        except SpendCapExceeded as e:
            log.warning("llm_spend_cap_degrade", error=str(e))
            return self._fallback(signal, "spend_cap")

        if not result:
            return self._fallback(signal, "fallback")

        return Validation(
            approved=bool(result.get("approve", False)),
            confidence=float(result.get("confidence", 0.0)),
            reasoning=str(result.get("reasoning", ""))[:500],
            adjusted_stop=result.get("adjusted_stop"),
            source="llm",
        )
