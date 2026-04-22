"""LLM-backed validation service.

Sits between SignalService and RiskEngine: approves or rejects a signal by
asking the LLM through ``LLMClient``. Falls back to a confidence-threshold
rule whenever the LLM is disabled, the spend cap is hit, or the call fails.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.core.logging import get_logger
from app.exceptions.domain import SpendCapExceededException
from app.services.llm_client import LLMClient
from app.strategies.base import Signal

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
    """Outcome of a validation pass over a single signal."""

    approved: bool
    confidence: float
    reasoning: str
    adjusted_stop: float | None = None
    source: str = "llm"  # "llm" | "disabled" | "fallback" | "spend_cap"


class ValidationService:
    """Validate a signal via LLM, with a confidence-threshold fallback."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        """Initialise the service.

        Args:
            llm: Optional ``LLMClient`` override. Defaults to a new instance.
        """
        self.llm = llm or LLMClient()

    def _fallback(self, sig: Signal, tag: str) -> Validation:
        """Build a non-LLM Validation using the strategy's own confidence."""
        s = get_settings()
        approved = sig.confidence >= s.ai_fallback_approve_threshold
        return Validation(approved, sig.confidence, tag, source=tag)

    def validate(
        self,
        signal: Signal,
        rag_context: list[str] | None = None,
        regime: str | None = None,
        corroborating_count: int = 0,
    ) -> Validation:
        """Validate a signal via LLM or fallback.

        Args:
            signal: Trading signal to validate.
            rag_context: Similar past trade descriptions to feed the LLM.
            regime: Current market regime (e.g. ``"trend_up"``, ``"range"``).
            corroborating_count: Number of strategies that fired the same
                side this tick (2+ means ensemble agreement).

        Returns:
            ``Validation`` with approval flag, confidence, reasoning, and
            optional adjusted stop.
        """
        s = get_settings()

        if not s.openrouter_enabled:
            return self._fallback(signal, "disabled")

        rag_block = ""
        if rag_context:
            rag_block = "\n\nSimilar past trades:\n- " + "\n- ".join(rag_context[:5])

        regime_line = f"Market regime: {regime}" if regime else ""
        corroboration_line = (
            f"Corroborating strategies this tick: {corroborating_count}"
            if corroborating_count > 1
            else ""
        )
        extra = "\n".join(filter(None, [regime_line, corroboration_line]))
        if extra:
            extra = "\n" + extra

        user = (
            f"Symbol: {signal.symbol}\n"
            f"Strategy: {signal.strategy}\n"
            f"Side: {signal.side}\n"
            f"Entry: {signal.entry}\n"
            f"Stop: {signal.stop_loss}\n"
            f"Target: {signal.target}\n"
            f"Strategy confidence: {signal.confidence:.2f}\n"
            f"Indicators: {signal.context}"
            f"{extra}"
            f"{rag_block}"
        )
        system = _PRESETS.get(s.agent_preset, _PRESETS["balanced"])

        log.debug(
            "llm_validating",
            symbol=signal.symbol,
            strategy=signal.strategy,
            side=signal.side,
            confidence=signal.confidence,
        )
        try:
            result = self.llm.chat_json(system, user, SCHEMA_HINT)
        except SpendCapExceededException as e:
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
