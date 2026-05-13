"""Pydantic request/response models used by the HTTP layer.

``ApiResponse[T]`` is the canonical envelope returned by every router
handler. Domain-specific response DTOs (``TradeOut``, ``SignalOut``,
``ReportOut``, ...) live alongside the routers that consume them.
"""

from __future__ import annotations

from app.models.api.admin import (
    AngelTotpOut,
    BrokerStatusOut,
    KillSwitchOut,
    PositionsOut,
)
from app.models.api.analyze import (
    AnalyzeOut,
    AnalyzeRequest,
    Candle,
    LiveAnalyzeOut,
    LiveAnalyzeRequest,
)
from app.models.api.audit import AuditLogListOut, AuditLogOut
from app.models.api.config import ConfigPatchOut, ConfigReloadOut
from app.models.api.order import OrderResultOut
from app.models.api.report import ReportBucket, ReportOut, ReportSummary
from app.models.api.response import ApiResponse
from app.models.api.scheduler import RunnerStartOut, RunnerStatusOut, RunnerStopOut
from app.models.api.signal import SignalListOut, SignalOut
from app.models.api.trade import TradeLifecycleOut, TradeListOut, TradeOut

__all__ = [
    "AngelTotpOut",
    "AnalyzeOut",
    "AnalyzeRequest",
    "ApiResponse",
    "AuditLogListOut",
    "AuditLogOut",
    "BrokerStatusOut",
    "Candle",
    "ConfigPatchOut",
    "ConfigReloadOut",
    "KillSwitchOut",
    "LiveAnalyzeOut",
    "LiveAnalyzeRequest",
    "OrderResultOut",
    "PositionsOut",
    "ReportBucket",
    "ReportOut",
    "ReportSummary",
    "RunnerStartOut",
    "RunnerStatusOut",
    "RunnerStopOut",
    "SignalListOut",
    "SignalOut",
    "TradeLifecycleOut",
    "TradeListOut",
    "TradeOut",
]
