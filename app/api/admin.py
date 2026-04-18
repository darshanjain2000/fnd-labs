from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_broker, get_risk_engine
from app.config import get_settings
from app.engine.risk_engine import RiskEngine
from app.services.broker.base import Broker

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/positions")
def positions(risk: RiskEngine = Depends(get_risk_engine)) -> dict:
    return {
        "open_positions": risk.stats.open_positions,
        "trades_today": risk.stats.trades_today,
        "realized_pnl_today": risk.stats.realized_pnl_today,
        "last_reset": str(risk.stats.last_reset),
    }


@router.post("/killswitch/{state}")
def killswitch(state: str, risk: RiskEngine = Depends(get_risk_engine)) -> dict:
    desired = state.lower() in ("on", "true", "1")
    risk.s.kill_switch = desired
    return {"kill_switch": desired}


@router.get("/broker/status")
def broker_status(broker: Broker = Depends(get_broker)) -> dict:
    """Verify the active broker is reachable. For Angel: calls profile()."""
    s = get_settings()
    info: dict = {
        "configured_broker": s.broker,
        "paper_trade_flag": s.paper_trade,
        "active_mode": broker.mode,
        "active_class": type(broker).__name__,
    }
    probe = getattr(broker, "profile", None)
    if callable(probe):
        info["probe"] = probe()
    else:
        info["probe"] = {"ok": True, "note": "no probe() on this broker"}
    return info

