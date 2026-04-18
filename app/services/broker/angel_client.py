"""Angel One SmartAPI broker skeleton.

SmartAPI is free (unlike Kite's ₹2000/mo). Requires:
  - Angel One demat account
  - API key from https://smartapi.angelbroking.com
  - TOTP secret for daily login (pyotp)

Dependencies (install when activating live mode):
  pip install smartapi-python pyotp logzero websocket-client

Set env vars:
  ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET
"""
from __future__ import annotations

import os
from typing import Any

from app.core.logging import get_logger
from app.services.broker.base import Broker, OrderRequest, OrderResult

log = get_logger(__name__)


class AngelBroker(Broker):
    mode = "live"

    def __init__(self) -> None:
        try:
            import pyotp  # type: ignore
            from SmartApi import SmartConnect  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "Install Angel SmartAPI deps: pip install smartapi-python pyotp"
            ) from e

        api_key = os.environ.get("ANGEL_API_KEY", "")
        client_code = os.environ.get("ANGEL_CLIENT_CODE", "")
        pin = os.environ.get("ANGEL_PIN", "")
        totp_secret = os.environ.get("ANGEL_TOTP_SECRET", "")
        if not all((api_key, client_code, pin, totp_secret)):
            raise RuntimeError("Set ANGEL_API_KEY / CLIENT_CODE / PIN / TOTP_SECRET")

        self._api = SmartConnect(api_key=api_key)
        totp = pyotp.TOTP(totp_secret).now()
        session = self._api.generateSession(client_code, pin, totp)
        if not session.get("status"):
            raise RuntimeError(f"angel login failed: {session}")
        self._client_code = client_code
        log.info("angel_logged_in", client=client_code)

    def place_order(self, req: OrderRequest) -> OrderResult:
        params: dict[str, Any] = {
            "variety": "NORMAL",
            "tradingsymbol": req.symbol,
            "symboltoken": req.symbol,  # caller supplies token in symbol; resolve via instruments dump
            "transactiontype": req.side,
            "exchange": "NFO",
            "ordertype": req.order_type.replace("SL-M", "STOPLOSS_MARKET").replace("SL", "STOPLOSS_LIMIT"),
            "producttype": "INTRADAY" if req.product == "MIS" else "CARRYFORWARD",
            "duration": "DAY",
            "quantity": str(req.qty),
        }
        if req.price is not None:
            params["price"] = str(req.price)
        if req.trigger_price is not None:
            params["triggerprice"] = str(req.trigger_price)

        order_id = self._api.placeOrder(params)
        log.info("angel_order_placed", order_id=order_id, **params)
        return OrderResult(order_id=str(order_id), status="OPEN", avg_price=0.0, filled_qty=0)

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._api.cancelOrder(order_id=order_id, variety="NORMAL")
            return True
        except Exception as e:  # pragma: no cover
            log.warning("angel_cancel_failed", order_id=order_id, error=str(e))
            return False

    def get_quote(self, symbol: str) -> float:
        q = self._api.ltpData("NFO", symbol, symbol)
        return float(q["data"]["ltp"])
