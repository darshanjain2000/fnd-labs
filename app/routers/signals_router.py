"""Strategy-signal list endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from app.dal.signal_dal import SignalDAL
from app.models.api import ApiResponse, SignalListOut, SignalOut

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=ApiResponse[SignalListOut])
def list_signals(limit: int = 50) -> ApiResponse[SignalListOut]:
    """List the most recent strategy signals (with AI verdicts)."""
    rows = SignalDAL().list_recent(limit=limit)
    payload = SignalListOut(count=len(rows), signals=[SignalOut.from_row(r) for r in rows])
    return ApiResponse[SignalListOut].ok(payload)
