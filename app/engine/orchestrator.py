"""Orchestrator: Signal -> Validation (AI) -> Risk -> Execution (with DB persistence)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.agents.execution_agent import ExecutionAgent
from app.agents.signal_agent import SignalAgent
from app.agents.validation_agent import ValidationAgent
from app.core.logging import get_logger
from app.db import SessionLocal
from app.engine.risk_engine import RiskEngine
from app.models.trade import Signal as SignalRow
from app.models.trade import Trade as TradeRow
from app.rag.store import RAGStore
from app.services.broker.base import Broker
from app.strategies.base import Signal

log = get_logger(__name__)


@dataclass
class PipelineOutcome:
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


class Orchestrator:
    def __init__(
        self,
        broker: Broker,
        risk_engine: RiskEngine | None = None,
        signal_agent: SignalAgent | None = None,
        validation_agent: ValidationAgent | None = None,
        rag: RAGStore | None = None,
        lot_size: int = 1,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self.broker = broker
        self.risk = risk_engine or RiskEngine()
        self.signal_agent = signal_agent or SignalAgent()
        self.validation_agent = validation_agent or ValidationAgent()
        self.execution_agent = ExecutionAgent(broker, session_factory=session_factory)
        self.rag = rag or RAGStore()
        self.lot_size = lot_size
        self._session_factory = session_factory

    def run(self, symbol: str, candles: pd.DataFrame, is_expiry_day: bool = False) -> list[PipelineOutcome]:
        signals = self.signal_agent.generate(symbol, candles)
        return [self._process_one(sig, is_expiry_day) for sig in signals]

    # ---- internal ---------------------------------------------------------
    def _persist_signal(self, sig: Signal, ai_approved: bool | None, ai_reasoning: str | None) -> int:
        with self._session_factory() as session:
            row = SignalRow(
                symbol=sig.symbol,
                strategy=sig.strategy,
                side=sig.side,
                confidence=sig.confidence,
                context=sig.context or {},
                ai_approved=ai_approved,
                ai_reasoning=ai_reasoning,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id

    def _process_one(self, sig: Signal, is_expiry_day: bool) -> PipelineOutcome:
        context_docs = self.rag.query_similar(
            f"{sig.symbol} {sig.strategy} {sig.side} ctx={sig.context}", k=3
        )
        validation = self.validation_agent.validate(sig, context_docs)

        sig_dict = {
            "symbol": sig.symbol, "strategy": sig.strategy, "side": sig.side,
            "entry": sig.entry, "stop_loss": sig.stop_loss, "target": sig.target,
            "confidence": sig.confidence, "context": sig.context,
        }

        signal_id = self._persist_signal(sig, validation.approved, validation.reasoning)

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

        with self._session_factory() as session:
            trade_id = session.query(TradeRow.id).filter(TradeRow.broker_order_id == result.order_id).scalar()

        return PipelineOutcome(
            signal=sig_dict, signal_id=signal_id,
            ai_approved=True, ai_reasoning=validation.reasoning,
            risk_approved=True, risk_reason="ok", qty=risk.qty,
            executed=True, trade_id=trade_id,
            order_id=result.order_id, fill_price=result.avg_price,
        )
