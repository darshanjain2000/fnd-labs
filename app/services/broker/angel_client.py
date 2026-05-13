"""Angel One SmartAPI broker.

SmartAPI is free. Requires an Angel demat account + an app created at
https://smartapi.angelone.in/new/apps

Form values to use when creating the app:
  App Name        : anything (e.g. "trading-poc")
  Redirect URL    : http://127.0.0.1:8000/angel/callback
  Post back URL   : leave blank
  Primary IP      : your PUBLIC IP (not your LAN 192.168.x.x)

Dependencies (only installed when going live):
    pip install smartapi-python pyotp logzero websocket-client

Settings used:
    ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.core.logging import get_logger
from app.services.broker.base import Broker, OrderRequest, OrderResult

log = get_logger(__name__)

# Angel uses its own order-type names. Map ours -> theirs.
_ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "STOPLOSS_LIMIT",
    "SL-M": "STOPLOSS_MARKET",
}
_PRODUCT_MAP = {"MIS": "INTRADAY", "NRML": "CARRYFORWARD", "CNC": "DELIVERY"}


class AngelBroker(Broker):
    """Live broker. DO NOT instantiate unless PAPER_TRADE=false and keys are set."""

    mode = "live"

    def __init__(self, smart_connect: Any | None = None) -> None:
        s = get_settings()
        missing = [
            k
            for k, v in {
                "ANGEL_API_KEY": s.angel_api_key,
                "ANGEL_CLIENT_CODE": s.angel_client_code,
                "ANGEL_PIN": s.angel_pin,
                "ANGEL_TOTP_SECRET": s.angel_totp_secret,
            }.items()
            if not v
        ]
        if missing:
            raise RuntimeError(f"Angel credentials missing: {', '.join(missing)}")

        self._api = smart_connect if smart_connect is not None else self._real_login(s)
        self._client_code = s.angel_client_code
        self._token_cache: dict[str, str] = {}
        log.info("angel_logged_in", client=s.angel_client_code)

    # ---- login -----------------------------------------------------------
    @staticmethod
    def _real_login(s: Any) -> Any:
        try:
            import pyotp  # type: ignore
            from SmartApi import SmartConnect  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "Install Angel deps: pip install smartapi-python pyotp"
            ) from e

        api = SmartConnect(api_key=s.angel_api_key)
        totp = pyotp.TOTP(s.angel_totp_secret).now()
        session = api.generateSession(s.angel_client_code, s.angel_pin, totp)
        if not session.get("status"):
            raise RuntimeError(f"angel login failed: {session}")
        return api

    # ---- token resolution -------------------------------------------------
    def resolve_token(self, tradingsymbol: str, exchange: str = "NFO") -> str:
        """Look up numeric symboltoken Angel needs for every order."""
        if tradingsymbol in self._token_cache:
            return self._token_cache[tradingsymbol]
        res = self._api.searchScrip(exchange=exchange, searchtext=tradingsymbol)
        data = res.get("data") if isinstance(res, dict) else None
        if not data:
            raise RuntimeError(f"angel token not found for {tradingsymbol}")
        token = str(data[0].get("symboltoken") or data[0].get("token"))
        self._token_cache[tradingsymbol] = token
        return token

    # ---- broker API -------------------------------------------------------
    def place_order(self, req: OrderRequest) -> OrderResult:
        token = self.resolve_token(req.symbol)
        params: dict[str, Any] = {
            "variety": "STOPLOSS" if req.order_type in ("SL", "SL-M") else "NORMAL",
            "tradingsymbol": req.symbol,
            "symboltoken": token,
            "transactiontype": req.side,
            "exchange": "NFO",
            "ordertype": _ORDER_TYPE_MAP[req.order_type],
            "producttype": _PRODUCT_MAP[req.product],
            "duration": "DAY",
            "quantity": str(req.qty),
        }
        if req.price is not None:
            params["price"] = str(req.price)
        if req.trigger_price is not None:
            params["triggerprice"] = str(req.trigger_price)

        try:
            order_id = self._api.placeOrder(params)
        except Exception as e:
            log.warning("angel_order_failed", error=str(e), symbol=req.symbol)
            return OrderResult(
                order_id="",
                status="REJECTED",
                avg_price=0.0,
                filled_qty=0,
                message=str(e),
            )
        log.info(
            "angel_order_placed",
            order_id=order_id,
            symbol=req.symbol,
            side=req.side,
            qty=req.qty,
        )
        return OrderResult(
            order_id=str(order_id), status="OPEN", avg_price=0.0, filled_qty=0
        )

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._api.cancelOrder(order_id=order_id, variety="NORMAL")
            return True
        except Exception as e:  # pragma: no cover
            log.warning("angel_cancel_failed", order_id=order_id, error=str(e))
            return False

    def get_quote(self, symbol: str) -> float:
        token = self.resolve_token(symbol)
        q = self._api.ltpData("NFO", symbol, token)
        return float(q["data"]["ltp"])

    # ---- diagnostics ------------------------------------------------------
    def profile(self) -> dict[str, Any]:
        """Lightweight health check: returns Angel profile payload."""
        try:
            p = (
                self._api.getProfile(refreshToken=None)
                if hasattr(self._api, "getProfile")
                else {}
            )
            return {"ok": True, "client_code": self._client_code, "profile": p}
        except Exception as e:
            return {"ok": False, "error": str(e)}
