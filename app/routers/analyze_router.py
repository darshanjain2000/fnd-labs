"""Pipeline analysis endpoints (client-supplied candles or live Angel fetch)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.engine.orchestrator import Orchestrator
from app.exceptions.domain import DataNotFoundException, InvalidRequestException
from app.models.api import (
    AnalyzeOut,
    AnalyzeRequest,
    ApiResponse,
    LiveAnalyzeOut,
    LiveAnalyzeRequest,
)
from app.routers.deps import get_orchestrator, set_mock_quote
from app.services.market_data import compute_indicators

router = APIRouter(prefix="/analyze", tags=["analyze"])


@router.post("", response_model=ApiResponse[AnalyzeOut])
def analyze(
    req: AnalyzeRequest,
    orch: Orchestrator = Depends(get_orchestrator),
) -> ApiResponse[AnalyzeOut]:
    """Run the full pipeline against a client-supplied candle batch."""
    import pandas as pd

    if req.mock_quote is not None:
        set_mock_quote(req.symbol, req.mock_quote)

    df = pd.DataFrame([c.model_dump() for c in req.candles])
    if df.empty:
        raise InvalidRequestException("no candles supplied")

    df = compute_indicators(df)
    outcomes = orch.run(req.symbol, df, is_expiry_day=req.is_expiry_day)
    return ApiResponse[AnalyzeOut].ok(
        AnalyzeOut(symbol=req.symbol, outcomes=[o.__dict__ for o in outcomes])
    )


@router.post("/live", response_model=ApiResponse[LiveAnalyzeOut])
def analyze_live(
    req: LiveAnalyzeRequest,
    orch: Orchestrator = Depends(get_orchestrator),
) -> ApiResponse[LiveAnalyzeOut]:
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
        raise DataNotFoundException(f"Angel data fetch failed: {exc}") from exc

    if len(df) < 20:
        raise InvalidRequestException(
            f"Too few candles returned ({len(df)}) — try a wider date range or longer interval"
        )

    last_price = float(df["close"].iloc[-1])
    set_mock_quote(req.symbol, last_price)

    df = compute_indicators(df)
    outcomes = orch.run(req.symbol, df, is_expiry_day=req.is_expiry_day)

    return ApiResponse[LiveAnalyzeOut].ok(
        LiveAnalyzeOut(
            symbol=req.symbol,
            exchange=req.exchange,
            interval=req.interval,
            candles_used=len(df),
            last_close=last_price,
            outcomes=[o.__dict__ for o in outcomes],
        )
    )
