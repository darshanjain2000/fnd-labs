from __future__ import annotations

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
