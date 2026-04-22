"""Back-compat facade over :class:`app.services.validation_service.ValidationService`.

Phase 3 moved the validation logic into ``ValidationService``. This module
stays as a thin alias so existing imports keep working until Phase 5
deletes ``app/agents/``.
"""
from __future__ import annotations

from app.services.validation_service import Validation, ValidationService


class ValidationAgent(ValidationService):
    """Alias for :class:`ValidationService`. Prefer the service name in new code."""


__all__ = ["Validation", "ValidationAgent"]
