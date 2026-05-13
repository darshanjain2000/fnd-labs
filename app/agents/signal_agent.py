"""Back-compat facade over :class:`app.services.signal_service.SignalService`.

Phase 3 moved the signal-generation logic into ``SignalService``. This
module stays as a thin alias so existing imports keep working during the
rest of the revamp; Phase 5 deletes ``app/agents/`` entirely.
"""

from __future__ import annotations

from app.services.signal_service import SignalService


class SignalAgent(SignalService):
    """Alias for :class:`SignalService`. Prefer the service name in new code."""


__all__ = ["SignalAgent"]
