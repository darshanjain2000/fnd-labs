"""Controllers — thin delegation layer between routers and services.

Per AGENTS.md §5, controllers coordinate services and DAL reads, shape
results for the transport layer, and map domain exceptions into API
responses. They never hold business logic themselves.
"""
from __future__ import annotations

from app.controllers.execution_controller import ExecutionController
from app.controllers.signal_controller import SignalController
from app.controllers.trade_controller import TradeController
from app.controllers.validation_controller import ValidationController

__all__ = [
    "ExecutionController",
    "SignalController",
    "TradeController",
    "ValidationController",
]
