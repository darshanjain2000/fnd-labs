"""Angel One SmartAPI session manager.

Provides a shared, lazily-initialised SmartConnect session used by BOTH:
  - AngelBroker  (live order placement)
  - market_data  (historical candles — needed even in paper mode)

Usage
-----
    from app.services.angel_session import get_angel_session
    sess = get_angel_session()           # logs in on first call
    candles = sess.candles("NFO", "99926004", "FIVE_MINUTE", from_dt, to_dt)
    token   = sess.resolve_token("NFO", "NIFTY25APR22500CE")

Intervals accepted by Angel
---------------------------
  ONE_MINUTE THREE_MINUTE FIVE_MINUTE TEN_MINUTE FIFTEEN_MINUTE
  THIRTY_MINUTE ONE_HOUR ONE_DAY
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

import pandas as pd

from app.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_INTERVAL_MAP = {
    "1m":  "ONE_MINUTE",
    "3m":  "THREE_MINUTE",
    "5m":  "FIVE_MINUTE",
    "10m": "TEN_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE",
    "1h":  "ONE_HOUR",
    "1d":  "ONE_DAY",
}


class AngelSession:
    """Thread-safe, lazily-logged-in wrapper around SmartConnect."""

    def __init__(self) -> None:
        self._api: Any | None = None
        self._token_cache: dict[str, str] = {}
        self._login_lock = threading.Lock()  # prevents concurrent login races

    # ---- login -----------------------------------------------------------
    def _ensure_logged_in(self) -> Any:
        # Fast path — already logged in (no lock needed for reads after init).
        if self._api is not None:
            return self._api
        # Slow path — acquire lock so only one thread does the login.
        with self._login_lock:
            if self._api is not None:
                return self._api  # another thread won the race — reuse its session
            s = get_settings()
            # Defensive strip — .env values often have trailing spaces
            api_key = (s.angel_api_key or "").strip()
            client  = (s.angel_client_code or "").strip()
            pin     = (s.angel_pin or "").strip()
            secret  = (s.angel_totp_secret or "").strip().replace(" ", "").upper()

            missing = [k for k, v in {
                "ANGEL_API_KEY": api_key,
                "ANGEL_CLIENT_CODE": client,
                "ANGEL_PIN": pin,
                "ANGEL_TOTP_SECRET": secret,
            }.items() if not v]
            if missing:
                raise RuntimeError(
                    f"Angel credentials not set — add to .env: {', '.join(missing)}"
                )
            try:
                import pyotp  # type: ignore
                from SmartApi import SmartConnect  # type: ignore
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("pip install smartapi-python pyotp") from e

            try:
                totp = pyotp.TOTP(secret).now()
            except Exception as e:
                raise RuntimeError(
                    f"ANGEL_TOTP_SECRET is not a valid base32 string. "
                    f"You must paste the SECRET from smartapi.angelone.in/enable-totp "
                    f"(looks like 'JBSWY3DPEHPK3PXP...'), NOT the 6-digit code. ({e})"
                ) from e

            api = SmartConnect(api_key=api_key)
            session = api.generateSession(client, pin, totp)
            if not session.get("status"):
                msg = session.get("message", session)
                hint = ""
                if "totp" in str(msg).lower() or session.get("errorcode") == "AB1050":
                    hint = (
                        " — HINT: This usually means (a) ANGEL_TOTP_SECRET doesn't match "
                        "the currently-enrolled secret on smartapi.angelone.in/enable-totp "
                        "(re-enroll and copy the NEW secret), (b) system clock is skewed, "
                        "or (c) client code / PIN is wrong."
                    )
                raise RuntimeError(f"Angel login failed: {msg}{hint}")
            self._api = api
            log.info("angel_session_started", client=client)
            return self._api

    def reset(self) -> None:
        """Force re-login on next call (call after credentials change)."""
        self._api = None
        self._token_cache.clear()

    def ensure_ready(self) -> None:
        """Pre-warm the session so subsequent candle fetches skip login overhead.

        Call this once in the main thread (or a single thread) before launching
        parallel candle fetches. Ensures only one login attempt is made and all
        parallel requests start from an already-authenticated session.
        """
        self._ensure_logged_in()

    # ---- token resolution ------------------------------------------------
    # Angel's public scrip master (no auth; refreshed daily by Angel)
    _SCRIP_MASTER_URL = (
        "https://margincalculator.angelone.in/OpenAPI_File/files/"
        "OpenAPIScripMaster.json"
    )
    _scrip_master: list[dict] | None = None

    @classmethod
    def _load_scrip_master(cls) -> list[dict]:
        if cls._scrip_master is not None:
            return cls._scrip_master
        import json
        import urllib.request
        from pathlib import Path
        cache = Path(".cache/angel_scrip_master.json")
        cache.parent.mkdir(exist_ok=True)
        # Use daily cache to avoid re-downloading (file is ~50MB)
        if cache.exists():
            import time as _t
            age_hrs = (_t.time() - cache.stat().st_mtime) / 3600
            if age_hrs < 24:
                cls._scrip_master = json.loads(cache.read_text(encoding="utf-8"))
                log.info("scrip_master_loaded_from_cache", rows=len(cls._scrip_master))
                return cls._scrip_master
        log.info("scrip_master_downloading")
        with urllib.request.urlopen(cls._SCRIP_MASTER_URL, timeout=60) as r:
            raw = r.read().decode("utf-8")
        cache.write_text(raw, encoding="utf-8")
        cls._scrip_master = json.loads(raw)
        log.info("scrip_master_downloaded", rows=len(cls._scrip_master))
        return cls._scrip_master

    def resolve_token(self, exchange: str, tradingsymbol: str) -> str:
        key = f"{exchange}:{tradingsymbol}"
        if key in self._token_cache:
            return self._token_cache[key]

        # Primary path: local scrip-master lookup (works even with dormant account)
        try:
            master = self._load_scrip_master()
            sym_u = tradingsymbol.upper()
            # Map user exchange to Angel's exch_seg tag
            exch_map = {
                "NSE": "NSE", "BSE": "BSE", "NFO": "NFO", "BFO": "BFO",
                "MCX": "MCX", "CDS": "CDS",
                # lowercase variants from scrip master (older dumps use nse_cm etc.)
            }
            target = exch_map.get(exchange.upper(), exchange.upper())
            rows = [
                r for r in master
                if str(r.get("exch_seg", "")).upper() in (target, f"{target}_CM", f"{target}_FO")
            ]
            # For NSE/BSE index queries (e.g. "NIFTY", "BANKNIFTY"), prefer AMXIDX rows
            # — Angel stores the real index under symbol="Nifty 50", name="NIFTY".
            index_rows = [
                r for r in rows
                if str(r.get("instrumenttype", "")).upper() in ("AMXIDX", "INDEX")
                and str(r.get("name", "")).upper() == sym_u
            ]
            if index_rows:
                hit = index_rows[0]
            else:
                # Exact tradingsymbol match first
                hit = next((r for r in rows if str(r.get("symbol", "")).upper() == sym_u), None)
                # Then name-based exact match (equity without -EQ suffix etc.)
                if not hit:
                    hit = next((r for r in rows if str(r.get("name", "")).upper() == sym_u), None)
                # Then prefix match
                if not hit:
                    hit = next((r for r in rows if str(r.get("symbol", "")).upper().startswith(sym_u)), None)
            if hit:
                token = str(hit.get("token"))
                self._token_cache[key] = token
                log.debug("angel_token_resolved_local",
                          symbol=tradingsymbol, token=token, matched=hit.get("symbol"))
                return token
        except Exception as e:
            log.warning("scrip_master_lookup_failed", error=str(e))

        # Fallback path: live searchScrip API (may be blocked for dormant accounts)
        api = self._ensure_logged_in()
        try:
            res = api.searchScrip(exchange, tradingsymbol)
        except TypeError:
            try:
                res = api.searchScrip(exchange=exchange, searchscrip=tradingsymbol)
            except TypeError:
                res = api.searchScrip(exchange=exchange, searchtext=tradingsymbol)
        data = res.get("data") if isinstance(res, dict) else None
        if not data:
            raise RuntimeError(f"Angel token not found for {tradingsymbol} on {exchange}")
        token = str(data[0].get("symboltoken") or data[0].get("token"))
        self._token_cache[key] = token
        log.debug("angel_token_resolved", symbol=tradingsymbol, token=token)
        return token

    # ---- historical OHLCV ------------------------------------------------
    def candles(
        self,
        exchange: str,
        symboltoken: str,
        interval: str,
        from_dt: datetime,
        to_dt: datetime,
        symbol: str = "",
    ) -> pd.DataFrame:
        """Return a DataFrame with columns: datetime, open, high, low, close, volume."""
        api = self._ensure_logged_in()
        angel_interval = _INTERVAL_MAP.get(interval, interval)
        params = {
            "exchange": exchange,
            "symboltoken": symboltoken,
            "interval": angel_interval,
            "fromdate": from_dt.strftime("%Y-%m-%d %H:%M"),
            "todate": to_dt.strftime("%Y-%m-%d %H:%M"),
        }
        resp = api.getCandleData(params)
        if not resp.get("status") or not resp.get("data"):
            raise RuntimeError(f"Angel candle fetch failed: {resp}")
        data = resp["data"]
        df = pd.DataFrame(data, columns=["datetime", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        log.info(
            "angel_candles_fetched",
            symbol=symbol or symboltoken,
            token=symboltoken,
            interval=angel_interval,
            rows=len(df),
        )
        return df

    def fetch_candles_for_symbol(
        self,
        symbol: str,
        exchange: str = "NFO",
        interval: str = "5m",
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> pd.DataFrame:
        """Convenience: resolve token then fetch candles."""
        token = self.resolve_token(exchange, symbol)
        if to_dt is None:
            to_dt = datetime.now().replace(second=0, microsecond=0)
        if from_dt is None:
            # default lookback in CALENDAR days — generous enough to span weekends/holidays
            calendar_days = {
                "1m": 3, "3m": 5, "5m": 10, "10m": 15,
                "15m": 20, "30m": 30, "1h": 45, "1d": 180,
            }.get(interval, 10)
            from_dt = to_dt - timedelta(days=calendar_days)
        return self.candles(exchange, token, interval, from_dt, to_dt, symbol=symbol)


# ---- module-level singleton -----------------------------------------------
_SESSION: AngelSession | None = None


@lru_cache(maxsize=1)
def get_angel_session() -> AngelSession:
    return AngelSession()


def reset_angel_session() -> None:
    get_angel_session.cache_clear()
    global _SESSION
    _SESSION = None


# ---- helpers ---------------------------------------------------------------
def _sub_bars(dt: datetime, interval: str, bars: int) -> datetime:
    """Subtract `bars` intervals from dt."""
    from datetime import timedelta
    minutes = {
        "1m": 1, "3m": 3, "5m": 5, "10m": 10,
        "15m": 15, "30m": 30, "1h": 60, "1d": 1440,
    }.get(interval, 5)
    return dt - timedelta(minutes=minutes * bars)
