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


@router.get("/angel/totp")
def angel_totp_probe() -> dict:
    """Diagnostic: shows the 6-digit code your ANGEL_TOTP_SECRET generates RIGHT NOW.

    Compare this against the code in your Authenticator app for the Angel entry.
    If they DIFFER, your secret is wrong — re-enroll at
    https://smartapi.angelone.in/enable-totp and copy the NEW base32 secret.
    If they MATCH but login still fails with AB1050, your client code or PIN is wrong.
    """
    import time
    s = get_settings()
    secret = (s.angel_totp_secret or "").strip().replace(" ", "").upper()
    if not secret:
        return {"ok": False, "error": "ANGEL_TOTP_SECRET not set in .env"}
    try:
        import pyotp  # type: ignore
        t = pyotp.TOTP(secret)
        now = int(time.time())
        return {
            "ok": True,
            "current_code": t.now(),
            "previous_code": t.at(now - 30),
            "next_code": t.at(now + 30),
            "seconds_remaining": 30 - (now % 30),
            "client_code": (s.angel_client_code or "").strip(),
            "secret_length": len(secret),
            "note": "Open your Authenticator app — the 'current_code' MUST match the Angel entry.",
        }
    except Exception as e:
        return {"ok": False, "error": f"Invalid base32 secret: {e}"}


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

