"""Thin wrapper over kiteconnect. Kept minimal; expanded in Phase 1."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.core.logging import get_logger
from app.services.broker.base import Broker, OrderRequest, OrderResult

log = get_logger(__name__)


class KiteBroker(Broker):
    mode = "live"

    def __init__(self) -> None:
        try:
            from kiteconnect import KiteConnect  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("kiteconnect not installed") from e

        s = get_settings()
        if not (s.kite_api_key and s.kite_access_token):
            raise RuntimeError(
                "KITE_API_KEY and KITE_ACCESS_TOKEN must be set for live mode"
            )

        self._kite = KiteConnect(api_key=s.kite_api_key)
        self._kite.set_access_token(s.kite_access_token)

    def place_order(self, req: OrderRequest) -> OrderResult:
        k = self._kite
        params: dict[str, Any] = {
            "tradingsymbol": req.symbol,
            "exchange": "NFO",
            "transaction_type": req.side,
            "quantity": req.qty,
            "product": req.product,
            "order_type": req.order_type,
            "variety": "regular",
        }
        if req.price is not None:
            params["price"] = req.price
        if req.trigger_price is not None:
            params["trigger_price"] = req.trigger_price
        if req.tag:
            params["tag"] = req.tag[:20]

        order_id = k.place_order(**params)
        log.info("kite_order_placed", order_id=order_id, **params)
        return OrderResult(
            order_id=str(order_id), status="OPEN", avg_price=0.0, filled_qty=0
        )

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._kite.cancel_order(variety="regular", order_id=order_id)
            return True
        except Exception as e:  # pragma: no cover
            log.warning("kite_cancel_failed", order_id=order_id, error=str(e))
            return False

    def get_quote(self, symbol: str) -> float:
        q = self._kite.ltp([f"NFO:{symbol}"])
        return float(q[f"NFO:{symbol}"]["last_price"])
