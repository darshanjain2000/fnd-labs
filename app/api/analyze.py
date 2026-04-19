from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_orchestrator, set_mock_quote
from app.engine.orchestrator import Orchestrator
from app.services.market_data import compute_indicators

router = APIRouter(prefix="/analyze", tags=["analyze"])


class Candle(BaseModel):
    open: float
    high: float
    low: float
    close: float
    volume: float


class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., examples=["NIFTY24APR22500CE"])
    candles: list[Candle] = Field(..., min_length=20)
    is_expiry_day: bool = False
    mock_quote: float | None = None


class LiveAnalyzeRequest(BaseModel):
    symbol: str = Field(..., examples=["NIFTY25APR22500CE"])
    exchange: str = Field("NFO", examples=["NFO", "NSE", "BSE"])
    interval: str = Field("5m", examples=["1m", "3m", "5m", "15m", "30m", "1h"])
    from_dt: datetime | None = Field(None, description="Start datetime (default: 80 bars back)")
    to_dt: datetime | None = Field(None, description="End datetime (default: now)")
    is_expiry_day: bool = False


@router.post("")
def analyze(req: AnalyzeRequest, orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    import pandas as pd

    if req.mock_quote is not None:
        set_mock_quote(req.symbol, req.mock_quote)

    df = pd.DataFrame([c.model_dump() for c in req.candles])
    if df.empty:
        raise HTTPException(400, "no candles supplied")

    df = compute_indicators(df)
    outcomes = orch.run(req.symbol, df, is_expiry_day=req.is_expiry_day)
    return {"symbol": req.symbol, "outcomes": [o.__dict__ for o in outcomes]}


@router.post("/live")
def analyze_live(req: LiveAnalyzeRequest, orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    """Fetch real OHLCV from Angel One then run strategy → AI → risk → paper execution."""
    from app.services.angel_session import get_angel_session

    try:
        session = get_angel_session()
        df = session.fetch_candles_for_symbol(
            symbol=req.symbol,
            exchange=req.exchange,
            interval=req.interval,
            from_dt=req.from_dt,
            to_dt=req.to_dt,
        )
    except RuntimeError as exc:
        raise HTTPException(503, f"Angel data fetch failed: {exc}") from exc

    if len(df) < 20:
        raise HTTPException(422, f"Too few candles returned ({len(df)}) — try a wider date range or longer interval")

    # Use last close as the live quote for the paper broker
    last_price = float(df["close"].iloc[-1])
    set_mock_quote(req.symbol, last_price)

    df = compute_indicators(df)
    outcomes = orch.run(req.symbol, df, is_expiry_day=req.is_expiry_day)

    return {
        "symbol": req.symbol,
        "exchange": req.exchange,
        "interval": req.interval,
        "candles_used": len(df),
        "last_close": last_price,
        "outcomes": [o.__dict__ for o in outcomes],
    }

