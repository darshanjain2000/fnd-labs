"""Orchestrator: Signal -> Conviction filter -> Validation (AI) -> Risk -> Execution.

Phase 3 changes:
- Ensemble conviction: only trade when min_strategy_agreement strategies agree
  on the same side for a symbol. Picks the single best signal from the majority.
- Low-confidence signals (below min_signal_confidence) are dropped before counting.
- Signal memory window: recent signals are kept for ``signal_memory_ticks`` ticks
  so conviction can build across candles (e.g. RSI fires tick 1, EMA fires tick 3).
- At most ONE trade per symbol per tick.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.agents.execution_agent import ExecutionAgent
from app.agents.signal_agent import SignalAgent
from app.agents.validation_agent import ValidationAgent
from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.db import SessionLocal
from app.engine.regime_detector import detect_regime
from app.engine.risk_engine import RiskEngine
from app.memory.trade_memory import TradeMemory
from app.models.trade import Signal as SignalRow
from app.rag.store import RAGStore
from app.services.broker.base import Broker
from app.strategies.base import Signal

log = get_logger(__name__)


@dataclass
class PipelineOutcome:
    """Result of a single signal through the pipeline.

    Attributes:
        signal: Dict snapshot of the Signal fields.
        signal_id: DB row id of the persisted signal (or None).
        ai_approved: Whether the AI validation agent approved.
        ai_reasoning: Reasoning string from validation.
        risk_approved: Whether the risk engine approved.
        risk_reason: Machine-readable rejection reason or "ok".
        qty: Computed position size.
        executed: True if an order was placed.
        trade_id: DB row id of the opened trade (or None).
        order_id: Broker order id string (or None).
        fill_price: Average fill price (or None).
    """

    signal: dict[str, Any]
    signal_id: int | None
    ai_approved: bool | None
    ai_reasoning: str | None
    risk_approved: bool
    risk_reason: str
    qty: int
    executed: bool
    trade_id: int | None = None
    order_id: str | None = None
    fill_price: float | None = None


def select_best_signal(signals: list[Signal], settings: Settings) -> Signal | None:
    """Apply ensemble conviction filter and return the single best signal.

    Steps:
    1. Drop signals below ``min_signal_confidence``.
    2. Group remaining by side (BUY / SELL), count distinct strategies per side.
    3. Pick the side with the highest strategy count.
       - Ties: pick the side with higher average confidence.
    4. If best count < ``min_strategy_agreement`` → return None (no conviction).
    5. Return the highest-confidence signal from the winning side.

    Args:
        signals: Raw signals from the SignalAgent (may be empty).
        settings: Current application settings.

    Returns:
        The single best Signal to trade, or None if conviction is insufficient.
    """
    if not signals:
        return None

    min_conf = settings.min_signal_confidence
    min_agree = settings.min_strategy_agreement

    # Step 1: confidence gate
    strong = [s for s in signals if s.confidence >= min_conf]
    dropped = len(signals) - len(strong)
    if dropped:
        for s in signals:
            if s.confidence < min_conf:
                log.debug(
                    "signal_dropped_low_confidence",
                    symbol=s.symbol,
                    strategy=s.strategy,
                    side=s.side,
                    confidence=s.confidence,
                    threshold=min_conf,
                )
    if not strong:
        return None

    # Step 2: group by side
    by_side: dict[str, list[Signal]] = {}
    for s in strong:
        by_side.setdefault(s.side, []).append(s)

    # Step 3: pick best side
    side_counts = {side: len(sigs) for side, sigs in by_side.items()}
    best_side = max(
        side_counts,
        key=lambda side: (side_counts[side], _avg_confidence(by_side[side])),
    )
    best_count = side_counts[best_side]

    # Step 4: conviction gate
    if best_count < min_agree:
        log.info(
            "ensemble_insufficient",
            symbol=strong[0].symbol,
            side_counts=dict(side_counts),
            required=min_agree,
        )
        return None

    # Step 5: pick highest-confidence signal from the winning side
    winner = max(by_side[best_side], key=lambda s: s.confidence)
    log.info(
        "ensemble_selected",
        symbol=winner.symbol,
        side=best_side,
        agreement=best_count,
        total=len(strong),
        strategy=winner.strategy,
        confidence=winner.confidence,
    )
    return winner


def _avg_confidence(signals: list[Signal]) -> float:
    """Return mean confidence for a list of signals.

    Args:
        signals: Non-empty list of Signal instances.

    Returns:
        Average confidence value.
    """
    return sum(s.confidence for s in signals) / len(signals)


class Orchestrator:
    """Glues SignalAgent -> ensemble filter -> ValidationAgent -> RiskEngine -> ExecutionAgent."""

    def __init__(
        self,
        broker: Broker,
        risk_engine: RiskEngine | None = None,
        signal_agent: SignalAgent | None = None,
        validation_agent: ValidationAgent | None = None,
        rag: RAGStore | None = None,
        memory: TradeMemory | None = None,
        lot_size: int = 1,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        """Initialise the orchestrator.

        Args:
            broker: Broker instance (paper or live).
            risk_engine: Risk engine (defaults to RiskEngine with current settings).
            signal_agent: Strategy signal generator.
            validation_agent: LLM validation agent.
            rag: RAG store for similar-trade context.
            memory: SQL trade memory for similar-trade context.
            lot_size: F&O lot size for position sizing.
            session_factory: SQLAlchemy session factory.
        """
        self.broker = broker
        self.risk = risk_engine or RiskEngine()
        self.signal_agent = signal_agent or SignalAgent()
        self.validation_agent = validation_agent or ValidationAgent()
        self.execution_agent = ExecutionAgent(broker, session_factory=session_factory)
        self.rag = rag or RAGStore()
        self.memory = memory or TradeMemory(session_factory=session_factory)
        self.lot_size = lot_size
        self._session_factory = session_factory
        from app.dal.trade_dal import TradeDAL
        self._trade_dal = TradeDAL(session_factory=session_factory)
        # Signal memory: per-symbol deque of (tick_id, Signal) tuples
        self._signal_buffer: dict[str, deque[tuple[int, Signal]]] = {}
        self._tick_counter: int = 0
        # Per-symbol tick when a signal was last selected (for cooldown enforcement)
        self._last_signal_tick: dict[str, int] = {}

    def run(
        self,
        symbol: str,
        candles: pd.DataFrame,
        is_expiry_day: bool = False,
    ) -> list[PipelineOutcome]:
        """Run the full pipeline for *symbol*.

        1. Generate signals from all enabled strategies.
        2. Apply ensemble conviction filter (select_best_signal).
        3. Send the single best signal through AI -> Risk -> Execution.

        At most ONE trade per symbol per tick.

        Args:
            symbol: NSE trading symbol.
            candles: OHLCV DataFrame with indicators.
            is_expiry_day: Whether today is the contract expiry day.

        Returns:
            List of PipelineOutcome (0 or 1 element).
        """
        signals = self.signal_agent.generate(symbol, candles)
        log.debug("pipeline_stage_signals", symbol=symbol, count=len(signals))

        s = get_settings()
        self._tick_counter += 1

        # -- Cooldown: block new signals for signal_cooldown_ticks after last selected signal --
        cooldown = s.signal_cooldown_ticks
        last_tick = self._last_signal_tick.get(symbol)
        if last_tick is not None and cooldown > 0 and (self._tick_counter - last_tick) < cooldown:
            log.debug(
                "signal_skipped_cooldown",
                symbol=symbol,
                ticks_remaining=cooldown - (self._tick_counter - last_tick),
            )
            return []

        # -- Signal memory: merge current signals with recent buffer --
        merged = self._merge_with_buffer(symbol, signals, s)

        best = select_best_signal(merged, s)
        if best is None:
            return []

        self._last_signal_tick[symbol] = self._tick_counter
        regime = detect_regime(candles)
        corroborating = sum(1 for sig in merged if sig.side == best.side)
        return [self._process_one(best, is_expiry_day, regime=regime, corroborating_count=corroborating)]

    def _merge_with_buffer(
        self,
        symbol: str,
        new_signals: list[Signal],
        settings: Settings,
    ) -> list[Signal]:
        """Merge current tick's signals with the rolling signal memory buffer.

        Keeps only the most recent signal per strategy. Prunes entries older
        than ``signal_memory_ticks`` ticks.

        Args:
            symbol: The trading symbol.
            new_signals: Signals generated this tick.
            settings: Current application settings.

        Returns:
            Deduplicated list of recent signals (current + buffered).
        """
        window = settings.signal_memory_ticks
        if window <= 1:
            # Memory disabled — use only current tick signals
            return new_signals

        tick = self._tick_counter
        buf = self._signal_buffer.setdefault(symbol, deque())

        # Add new signals to buffer
        for sig in new_signals:
            buf.append((tick, sig))

        # Prune old entries
        cutoff = tick - window
        while buf and buf[0][0] <= cutoff:
            buf.popleft()

        # Deduplicate: keep most recent signal per strategy
        seen: dict[str, Signal] = {}
        for _tick_id, sig in buf:
            seen[sig.strategy] = sig

        merged = list(seen.values())
        if len(merged) > len(new_signals):
            log.info(
                "signal_memory_merged",
                symbol=symbol,
                current=len(new_signals),
                buffered=len(merged),
                window=window,
            )
        return merged

    # ---- internal ---------------------------------------------------------
    def _persist_signal(
        self,
        sig: Signal,
        ai_approved: bool | None,
        ai_reasoning: str | None,
        ai_confidence: float | None = None,
        ai_source: str | None = None,
    ) -> int:
        """Write a Signal row to the database.

        Args:
            sig: The trading signal.
            ai_approved: AI approval flag.
            ai_reasoning: AI reasoning text.
            ai_confidence: AI confidence score.
            ai_source: Source of validation ("llm", "fallback", etc.).

        Returns:
            Primary key of the inserted Signal row.
        """
        with self._session_factory() as session:
            row = SignalRow(
                symbol=sig.symbol,
                strategy=sig.strategy,
                side=sig.side,
                confidence=sig.confidence,
                context=sig.context or {},
                ai_approved=ai_approved,
                ai_reasoning=ai_reasoning,
                ai_confidence=ai_confidence,
                ai_source=ai_source,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id

    def _process_one(
        self,
        sig: Signal,
        is_expiry_day: bool,
        regime: str | None = None,
        corroborating_count: int = 1,
    ) -> PipelineOutcome:
        """Send a single signal through AI validation -> risk -> execution.

        Args:
            sig: The trading signal to process.
            is_expiry_day: Whether today is the contract expiry day.
            regime: Current market regime detected from candles.
            corroborating_count: Number of strategies that fired the same side.

        Returns:
            PipelineOutcome describing the result.
        """
        s = get_settings()
        if s.memory_source == "db":
            context_docs = self.memory.format_context(
                sig.symbol, sig.strategy, sig.side, k=s.memory_k
            )
        elif s.memory_source == "rag":
            context_docs = self.rag.query_similar(
                f"{sig.symbol} {sig.strategy} {sig.side} ctx={sig.context}", k=s.memory_k
            )
        else:
            context_docs = []
        validation = self.validation_agent.validate(
            sig, context_docs, regime=regime, corroborating_count=corroborating_count
        )

        sig_dict = {
            "symbol": sig.symbol, "strategy": sig.strategy, "side": sig.side,
            "entry": sig.entry, "stop_loss": sig.stop_loss, "target": sig.target,
            "confidence": sig.confidence, "context": sig.context,
        }

        signal_id = self._persist_signal(
            sig,
            validation.approved,
            validation.reasoning,
            ai_confidence=validation.confidence,
            ai_source=validation.source,
        )

        if not validation.approved:
            log.info("signal_rejected_by_ai", **sig_dict, reasoning=validation.reasoning)
            return PipelineOutcome(
                signal=sig_dict, signal_id=signal_id,
                ai_approved=False, ai_reasoning=validation.reasoning,
                risk_approved=False, risk_reason="ai_rejected", qty=0, executed=False,
            )

        if validation.adjusted_stop is not None:
            sig.stop_loss = float(validation.adjusted_stop)

        risk = self.risk.evaluate(sig, lot_size=self.lot_size, is_expiry_day=is_expiry_day)
        if not risk.approved:
            log.info("signal_rejected_by_risk", **sig_dict, reason=risk.reason)
            return PipelineOutcome(
                signal=sig_dict, signal_id=signal_id,
                ai_approved=True, ai_reasoning=validation.reasoning,
                risk_approved=False, risk_reason=risk.reason, qty=0, executed=False,
            )

        result = self.execution_agent.execute(sig, risk.qty, signal_row_id=signal_id)
        self.risk.record_trade_open()

        trade_id = self._trade_dal.find_by_broker_order_id(result.order_id)

        return PipelineOutcome(
            signal=sig_dict, signal_id=signal_id,
            ai_approved=True, ai_reasoning=validation.reasoning,
            risk_approved=True, risk_reason="ok", qty=risk.qty,
            executed=True, trade_id=trade_id,
            order_id=result.order_id, fill_price=result.avg_price,
        )
