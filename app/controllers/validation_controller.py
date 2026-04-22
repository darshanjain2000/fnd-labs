"""Controller for LLM signal validation."""
from __future__ import annotations

from app.services.validation_service import Validation, ValidationService
from app.strategies.base import Signal


class ValidationController:
    """Thin wrapper over :class:`ValidationService`."""

    def __init__(self, service: ValidationService | None = None) -> None:
        """Initialise the controller.

        Args:
            service: Injected service. Defaults to a new
                :class:`ValidationService`.
        """
        self._service = service or ValidationService()

    def validate(
        self,
        signal: Signal,
        rag_context: list[str] | None = None,
        regime: str | None = None,
        corroborating_count: int = 0,
    ) -> Validation:
        """Delegate to :meth:`ValidationService.validate`."""
        return self._service.validate(
            signal,
            rag_context=rag_context,
            regime=regime,
            corroborating_count=corroborating_count,
        )
