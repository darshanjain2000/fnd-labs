"""Controller for broker execution, close, and mark-to-market."""
from __future__ import annotations

from app.models.trade import Trade
from app.services.broker.base import Broker, OrderResult
from app.services.execution_service import ExecutionService
from app.strategies.base import Signal


class ExecutionController:
    """Thin wrapper over :class:`ExecutionService`."""

    def __init__(
        self,
        broker: Broker | None = None,
        *,
        service: ExecutionService | None = None,
    ) -> None:
        """Initialise the controller.

        Args:
            broker: Broker implementation to use when auto-constructing the
                service. Ignored when ``service`` is supplied.
            service: Injected service. Required when ``broker`` is ``None``.
        """
        if service is None:
            if broker is None:
                raise ValueError("ExecutionController requires either broker or service")
            service = ExecutionService(broker)
        self._service = service

    def execute(
        self,
        signal: Signal,
        qty: int,
        signal_row_id: int | None = None,
    ) -> OrderResult:
        """Delegate to :meth:`ExecutionService.execute`."""
        return self._service.execute(signal, qty, signal_row_id=signal_row_id)

    def close_trade(self, trade_id: int, exit_price: float) -> Trade | None:
        """Delegate to :meth:`ExecutionService.close_trade`."""
        return self._service.close_trade(trade_id, exit_price)

    def mark_to_market(
        self,
        latest_prices: dict[str, float],
        reason_tag: str = "mtm",
    ) -> list[Trade]:
        """Delegate to :meth:`ExecutionService.mark_to_market`."""
        return self._service.mark_to_market(latest_prices, reason_tag=reason_tag)

    def force_close_all(
        self,
        latest_prices: dict[str, float],
        reason: str = "square_off",
    ) -> list[Trade]:
        """Delegate to :meth:`ExecutionService.force_close_all`."""
        return self._service.force_close_all(latest_prices, reason=reason)
