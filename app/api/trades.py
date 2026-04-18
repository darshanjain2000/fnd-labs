"""Trades & signals read/close endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from api.deps import get_broker, get_risk_engine
from agents.execution_agent import ExecutionAgent
from db import get_session
from engine.risk_engine import RiskEngine
from models.trade import AuditLog, Signal, Trade
from services.broker.base import Broker

router = APIRouter(prefix="/trades", tags=["trades"])


class CloseRequest(BaseModel):
    exit_price: float


def _trade_dict(t: Trade) -> dict:
    return {
        "id": t.id, "signal_id": t.signal_id, "symbol": t.symbol, "side": t.side,
        "qty": t.qty, "entry_price": t.entry_price, "exit_price": t.exit_price,
        "stop_loss": t.stop_loss, "target": t.target, "pnl": t.pnl,
        "status": t.status, "mode": t.mode, "broker_order_id": t.broker_order_id,
        "opened_at": t.opened_at.isoformat() if t.opened_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
    }


@router.get("")
def list_trades(limit: int = 50, session: Session = Depends(get_session)) -> dict:
    rows = session.query(Trade).order_by(desc(Trade.opened_at)).limit(limit).all()
    return {"count": len(rows), "trades": [_trade_dict(t) for t in rows]}


@router.get("/{trade_id}")
def get_trade(trade_id: int, session: Session = Depends(get_session)) -> dict:
    t = session.get(Trade, trade_id)
    if not t:
        raise HTTPException(404, "trade not found")
    return _trade_dict(t)


@router.post("/{trade_id}/close")
def close_trade(
    trade_id: int,
    req: CloseRequest,
    broker: Broker = Depends(get_broker),
    risk: RiskEngine = Depends(get_risk_engine),
) -> dict:
    agent = ExecutionAgent(broker)
    t = agent.close_trade(trade_id, req.exit_price)
    if not t:
        raise HTTPException(404, "trade not found")
    if t.status == "CLOSED" and t.pnl is not None:
        risk.record_trade_close(t.pnl)
    return _trade_dict(t)


signals_router = APIRouter(prefix="/signals", tags=["signals"])


@signals_router.get("")
def list_signals(limit: int = 50, session: Session = Depends(get_session)) -> dict:
    rows = session.query(Signal).order_by(desc(Signal.created_at)).limit(limit).all()
    return {
        "count": len(rows),
        "signals": [
            {
                "id": r.id, "symbol": r.symbol, "strategy": r.strategy, "side": r.side,
                "confidence": r.confidence, "context": r.context,
                "ai_approved": r.ai_approved, "ai_reasoning": r.ai_reasoning,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


audit_router = APIRouter(prefix="/logs", tags=["logs"])


@audit_router.get("")
def list_audit(limit: int = 50, session: Session = Depends(get_session)) -> dict:
    rows = session.query(AuditLog).order_by(desc(AuditLog.at)).limit(limit).all()
    return {
        "count": len(rows),
        "logs": [
            {"id": r.id, "at": r.at.isoformat() if r.at else None, "event": r.event, "payload": r.payload}
            for r in rows
        ],
    }
