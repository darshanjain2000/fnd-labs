"""Load per-symbol optimized strategy parameters from YAML files.

Optimized parameter files are stored as ``config/params_{SYMBOL}.yaml``
(lower-cased symbol). Each file is a mapping of strategy name to a dict of
parameter values produced by ``optimize_all.py``.

Example file structure (``config/params_nifty.yaml``)::

    rsi_reversal:
      best_params:
        atr_mult: 1.8
        oversold: 28.0
        overbought: 72.0
      best_value: 14.2
    ema_breakout:
      best_params:
        atr_mult: 1.2
      best_value: 9.7

Usage::

    from app.core.optimized_params import load_params_for_symbol
    params = load_params_for_symbol("NIFTY")
    # {"rsi_reversal": {"atr_mult": 1.8, ...}, "ema_breakout": {...}, ...}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def params_file_for(symbol: str) -> Path:
    """Return the expected YAML path for *symbol*.

    Args:
        symbol: NSE trading symbol (e.g. "NIFTY").

    Returns:
        Path to ``config/params_{symbol_lower}.yaml``.
    """
    return _CONFIG_DIR / f"params_{symbol.lower()}.yaml"


def load_params_for_symbol(symbol: str) -> dict[str, dict[str, Any]]:
    """Return optimized strategy params for *symbol*, or an empty dict.

    Reads ``config/params_{symbol}.yaml`` when it exists. Each entry in the
    YAML is expected to contain a ``best_params`` sub-dict; only those values
    are returned (the metadata fields like ``best_value`` are stripped).

    Args:
        symbol: NSE trading symbol (e.g. "NIFTY").

    Returns:
        Mapping of ``{strategy_name: {param_name: value}}``.
        Returns ``{}`` if the file does not exist.
    """
    path = params_file_for(symbol)
    if not path.exists():
        return {}

    try:
        import yaml  # type: ignore

        with path.open() as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}
    except ImportError:
        with path.open() as fh:
            raw = json.load(fh)
    except Exception as exc:
        log.warning("optimized_params_load_failed", symbol=symbol, path=str(path), error=str(exc))
        return {}

    result: dict[str, dict[str, Any]] = {}
    for strategy_name, entry in raw.items():
        if isinstance(entry, dict):
            params = entry.get("best_params") or entry
            # Strip non-param metadata keys
            result[strategy_name] = {
                k: v for k, v in params.items() if k not in ("best_value", "metric", "strategy")
            }
    log.info("optimized_params_loaded", symbol=symbol, strategies=list(result.keys()))
    return result
