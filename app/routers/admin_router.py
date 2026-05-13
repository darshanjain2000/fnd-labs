"""Admin / diagnostics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.controllers.execution_controller import ExecutionController
from app.dal.trade_dal import TradeDAL
from app.engine.risk_engine import RiskEngine
from app.models.api import (
    AngelTotpOut,
    ApiResponse,
    BrokerStatusOut,
    KillSwitchOut,
    PositionsOut,
)
from app.routers.deps import get_broker, get_execution_controller, get_risk_engine
from app.services.angel_session import get_angel_session
from app.services.broker.base import Broker

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/positions", response_model=ApiResponse[PositionsOut])
def positions(
    risk: RiskEngine = Depends(get_risk_engine),
) -> ApiResponse[PositionsOut]:
    """Return the risk engine's in-memory daily stats snapshot."""
    return ApiResponse[PositionsOut].ok(
        PositionsOut(
            open_positions=risk.stats.open_positions,
            trades_today=risk.stats.trades_today,
            realized_pnl_today=risk.stats.realized_pnl_today,
            last_reset=str(risk.stats.last_reset),
        )
    )


@router.post("/killswitch/{state}", response_model=ApiResponse[KillSwitchOut])
def killswitch(
    state: str,
    risk: RiskEngine = Depends(get_risk_engine),
) -> ApiResponse[KillSwitchOut]:
    """Toggle the runtime kill switch on the risk engine."""
    desired = state.lower() in ("on", "true", "1")
    risk.s.kill_switch = desired
    return ApiResponse[KillSwitchOut].ok(KillSwitchOut(kill_switch=desired))


@router.get("/angel/totp", response_model=ApiResponse[AngelTotpOut])
def angel_totp_probe() -> ApiResponse[AngelTotpOut]:
    """Diagnostic: shows the 6-digit code ``ANGEL_TOTP_SECRET`` generates right now."""
    import time

    s = get_settings()
    secret = (s.angel_totp_secret or "").strip().replace(" ", "").upper()
    if not secret:
        return ApiResponse[AngelTotpOut].ok(
            AngelTotpOut(ok=False, error="ANGEL_TOTP_SECRET not set in .env")
        )
    try:
        import pyotp  # type: ignore

        t = pyotp.TOTP(secret)
        now = int(time.time())
        payload = AngelTotpOut(
            ok=True,
            current_code=t.now(),
            previous_code=t.at(now - 30),
            next_code=t.at(now + 30),
            seconds_remaining=30 - (now % 30),
            client_code=(s.angel_client_code or "").strip(),
            secret_length=len(secret),
            note="Open your Authenticator app - the 'current_code' MUST match the Angel entry.",
        )
        return ApiResponse[AngelTotpOut].ok(payload)
    except Exception as e:
        return ApiResponse[AngelTotpOut].ok(
            AngelTotpOut(ok=False, error=f"Invalid base32 secret: {e}")
        )


@router.get("/broker/status", response_model=ApiResponse[BrokerStatusOut])
def broker_status(
    broker: Broker = Depends(get_broker),
) -> ApiResponse[BrokerStatusOut]:
    """Verify the active broker is reachable (Angel: calls ``profile()``)."""
    s = get_settings()
    probe_fn = getattr(broker, "profile", None)
    probe = (
        probe_fn()
        if callable(probe_fn)
        else {"ok": True, "note": "no probe() on this broker"}
    )
    return ApiResponse[BrokerStatusOut].ok(
        BrokerStatusOut(
            configured_broker=s.broker,
            paper_trade_flag=s.paper_trade,
            active_mode=broker.mode,
            active_class=type(broker).__name__,
            probe=probe,
        )
    )


@router.post("/force-close-all", response_model=ApiResponse[dict])
def force_close_all(
    execution: ExecutionController = Depends(get_execution_controller),
    risk: RiskEngine = Depends(get_risk_engine),
) -> ApiResponse[dict]:
    """Immediately close every OPEN trade at the latest available price.

    Falls back to the trade's entry price if a live quote cannot be obtained.
    P&L and daily-loss counters are updated on the risk engine for each closed trade.

    Returns:
        ApiResponse with ``closed`` count and a list of per-trade summaries.
    """
    open_trades = TradeDAL().find_open()
    if not open_trades:
        return ApiResponse[dict].ok({"closed": 0, "trades": []})

    session = get_angel_session()
    latest_prices: dict[str, float] = {}
    for sym in {t.symbol for t in open_trades}:
        try:
            price = session.get_ltp(sym)
            if price:
                latest_prices[sym] = float(price)
        except Exception:
            pass

    for t in open_trades:
        if t.symbol not in latest_prices:
            latest_prices[t.symbol] = float(t.entry_price or 0)

    closed = execution.force_close_all(latest_prices, reason="manual_force_close")
    for t in closed:
        if t.pnl is not None:
            risk.record_trade_close(t.pnl)

    summaries = [
        {"id": t.id, "symbol": t.symbol, "pnl": t.pnl, "exit_price": t.exit_price}
        for t in closed
    ]
    return ApiResponse[dict].ok({"closed": len(closed), "trades": summaries})
