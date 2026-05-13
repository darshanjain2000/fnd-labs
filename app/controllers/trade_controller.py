"""Controller for trade read/close endpoints.

Trade reads have no business logic beyond a DAL call, so this controller
wraps :class:`TradeDAL` directly. The close path delegates to
:class:`ExecutionController` because it must place broker orders and
record PnL on the risk engine.
"""

from __future__ import annotations

from app.dal.trade_dal import TradeDAL
from app.models.trade import Trade


class TradeController:
    """Read-side trade queries; mutations live on :class:`ExecutionController`."""

    def __init__(self, dal: TradeDAL | None = None) -> None:
        """Initialise the controller.

        Args:
            dal: Injected DAL. Defaults to a new :class:`TradeDAL`.
        """
        self._dal = dal or TradeDAL()

    def list(self, limit: int = 50) -> list[Trade]:
        """Return the most recent trades, newest first."""
        return self._dal.list_recent(limit=limit)

    def get(self, trade_id: int) -> Trade:
        """Return the trade with the given id or raise ``TradeNotFoundException``."""
        return self._dal.get_by_id(trade_id)
