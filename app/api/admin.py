from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_risk_engine
from engine.risk_engine import RiskEngine

router = APIRouter(tags=["admin"])


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
