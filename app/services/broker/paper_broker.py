"""Paper broker: simulates fills at live quote + slippage. Same interface as Kite."""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable

from app.core.logging import get_logger
from app.services.broker.base import Broker, OrderRequest, OrderResult

log = get_logger(__name__)


class PaperBroker(Broker):
    mode = "paper"

    def __init__(
        self, quote_fn: Callable[[str], float], slippage_bps: float = 5.0
    ) -> None:
        self._quote_fn = quote_fn
        self._slippage_bps = slippage_bps
        self._orders: dict[str, OrderResult] = {}

    def _slip(self, price: float, side: str) -> float:
        slip = price * (self._slippage_bps / 10_000.0)
        jitter = random.uniform(0, slip)
        return price + jitter if side == "BUY" else price - jitter

    def place_order(self, req: OrderRequest) -> OrderResult:
        px = (
            req.price
            if req.order_type == "LIMIT" and req.price
            else self._quote_fn(req.symbol)
        )
        fill = round(self._slip(px, req.side), 2)
        order_id = f"PAPER-{uuid.uuid4().hex[:10]}"
        result = OrderResult(
            order_id=order_id,
            status="COMPLETE",
            avg_price=fill,
            filled_qty=req.qty,
            message="paper fill",
        )
        self._orders[order_id] = result
        log.info(
            "paper_order_filled",
            symbol=req.symbol,
            side=req.side,
            qty=req.qty,
            price=fill,
            tag=req.tag,
        )
        return result

    def cancel_order(self, order_id: str) -> bool:
        return self._orders.pop(order_id, None) is not None

    def get_quote(self, symbol: str) -> float:
        return self._quote_fn(symbol)
