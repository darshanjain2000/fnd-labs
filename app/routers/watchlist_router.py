"""Watchlist CRUD — add / remove / list symbols in the live watchlist.

Mutations update the in-memory ``Settings`` singleton (same mechanism as
``PATCH /config``). Changes persist until the process restarts; to make them
permanent the user should also edit ``.env``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Query
from pydantic import BaseModel, field_validator

from app.config import get_settings
from app.core.logging import get_logger
from app.models.api.response import ApiResponse
from app.services.angel_session import get_angel_session

log = get_logger(__name__)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

_PARAMS_DIR = Path("config")
_ENV_PATH = Path(".env")
_ALL_STRATEGY_NAMES: list[str] = [
    "rsi_reversal",
    "ema_breakout",
    "vwap_pullback",
    "supertrend",
    "macd_divergence",
    "bollinger_squeeze",
    "orb_breakout",
]


def _optimization_status(symbol: str) -> dict[str, Any]:
    """Return how many strategies have been Optuna-optimized for a symbol.

    Args:
        symbol: NSE trading symbol (uppercase).

    Returns:
        Dict with ``exists``, ``strategies_optimized``, and ``optimized_strategies`` keys.
    """
    path = _PARAMS_DIR / f"params_{symbol.lower()}.yaml"
    if not path.exists():
        return {
            "yaml_exists": False,
            "strategies_optimized": 0,
            "optimized_strategies": [],
        }
    data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    names = [n for n in _ALL_STRATEGY_NAMES if data.get(n)]
    return {
        "yaml_exists": True,
        "strategies_optimized": len(names),
        "optimized_strategies": names,
    }


class AddSymbolRequest(BaseModel):
    """Request body for adding a symbol to the watchlist."""

    symbol: str
    exchange: str = "NSE"

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, v: str) -> str:
        return v.upper().strip()

    @field_validator("exchange")
    @classmethod
    def _upper_exchange(cls, v: str) -> str:
        return v.upper().strip()


def _persist_watchlist_to_env(watchlist_value: str) -> None:
    """Write the current WATCHLIST value into the root .env file.

    If ``WATCHLIST=...`` exists, it is updated in-place. Otherwise a new line
    is appended. Other env entries are preserved as-is.
    """
    lines: list[str] = []
    if _ENV_PATH.exists():
        lines = _ENV_PATH.read_text(encoding="utf-8").splitlines()
    updated = False
    out: list[str] = []
    for line in lines:
        if line.strip().startswith("WATCHLIST="):
            out.append(f"WATCHLIST={watchlist_value}")
            updated = True
        else:
            out.append(line)
    if not updated:
        out.append(f"WATCHLIST={watchlist_value}")
    _ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


@router.get("/search", response_model=ApiResponse[dict])
def search_symbols(
    q: str = Query(default="", description="Symbol/name query"),
    exchange: str = Query(default="", description="Optional exchange filter, e.g. NSE"),
    limit: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[dict]:
    """Search symbols from Angel's cached scrip master.

    Args:
        q: Free-text symbol/name query.
        exchange: Optional exchange filter.
        limit: Maximum rows to return.

    Returns:
        ApiResponse with ``results`` list and ``count``.
    """
    rows = get_angel_session().search_symbols(q, exchange=exchange or None, limit=limit)
    return ApiResponse[dict].ok({"results": rows, "count": len(rows)})


@router.get("", response_model=ApiResponse[dict])
def list_watchlist() -> ApiResponse[dict]:
    """Return the current watchlist with per-symbol optimization metadata.

    Returns:
        ApiResponse containing a ``symbols`` list and a ``total`` count.
    """
    s = get_settings()
    pairs = s.watchlist_pairs()
    items = [
        {
            "symbol": sym,
            "exchange": exch,
            "lot_size": s.default_lot_size,
            **_optimization_status(sym),
        }
        for sym, exch in pairs
    ]
    return ApiResponse[dict].ok({"symbols": items, "total": len(items)})


@router.post("", response_model=ApiResponse[dict])
def add_symbol(body: AddSymbolRequest) -> ApiResponse[dict]:
    """Add a symbol to the active watchlist (in-memory until next restart).

    Args:
        body: The ``symbol`` and ``exchange`` to add.

    Returns:
        ApiResponse confirming addition or indicating the symbol already exists.
    """
    s = get_settings()
    current_syms = {sym for sym, _ in s.watchlist_pairs()}
    if body.symbol in current_syms:
        return ApiResponse[dict].ok(
            {"added": False, "reason": "already_in_watchlist", "symbol": body.symbol}
        )
    new_entry = f"{body.symbol}:{body.exchange}"
    s.watchlist = f"{s.watchlist},{new_entry}" if s.watchlist else new_entry
    log.info("watchlist_symbol_added", symbol=body.symbol, exchange=body.exchange)
    return ApiResponse[dict].ok(
        {"added": True, "symbol": body.symbol, "exchange": body.exchange}
    )


@router.delete("/{symbol}", response_model=ApiResponse[dict])
def remove_symbol(symbol: str) -> ApiResponse[dict]:
    """Remove a symbol from the active watchlist.

    Args:
        symbol: The trading symbol to remove (case-insensitive).

    Returns:
        ApiResponse confirming removal with the remaining symbol count.
    """
    s = get_settings()
    sym = symbol.upper().strip()
    filtered = [(s_, e) for s_, e in s.watchlist_pairs() if s_ != sym]
    s.watchlist = ",".join(f"{s_}:{e}" for s_, e in filtered)
    log.info("watchlist_symbol_removed", symbol=sym, remaining=len(filtered))
    return ApiResponse[dict].ok(
        {"removed": True, "symbol": sym, "remaining": len(filtered)}
    )


@router.post("/persist", response_model=ApiResponse[dict])
def persist_watchlist() -> ApiResponse[dict]:
    """Persist the runtime watchlist into ``.env`` as ``WATCHLIST=...``.

    Returns:
        ApiResponse with ``persisted`` flag and current watchlist string.
    """
    s = get_settings()
    _persist_watchlist_to_env(s.watchlist)
    log.info("watchlist_persisted", watchlist=s.watchlist)
    return ApiResponse[dict].ok({"persisted": True, "watchlist": s.watchlist})
