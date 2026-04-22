"""Back-compat facade over :class:`app.services.execution_service.ExecutionService`.

Phase 3 moved the execution, close, and mark-to-market logic into
``ExecutionService`` so the agent no longer owns DB writes directly.
This module stays as a thin alias until Phase 5 deletes ``app/agents/``.
"""
from __future__ import annotations

from app.services.execution_service import ExecutionService


class ExecutionAgent(ExecutionService):
    """Alias for :class:`ExecutionService`. Prefer the service name in new code."""


__all__ = ["ExecutionAgent"]
