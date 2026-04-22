"""Signal generation service.

Runs all enabled strategies for a symbol, applies the regime filter, and
optionally enforces higher-timeframe EMA agreement. Pure business logic —
no DB access, no broker calls.
"""
from __future__ import annotations

import pandas as pd

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.optimized_params import load_params_for_symbol
from app.engine.regime_detector import detect_regime
from app.strategies import ALL_STRATEGIES, Signal
from app.strategies.base import Strategy

log = get_logger(__name__)


def _htf_agrees(signal: Signal, htf_candles: pd.DataFrame | None) -> bool:
    """Return True when HTF EMA trend direction aligns with ``signal``.

    Args:
        signal: The signal whose side to validate.
        htf_candles: Higher-timeframe OHLCV frame with ema20/ema50 columns.

    Returns:
        True if HTF agrees (or data is missing — pass-through), else False.
    """
    if htf_candles is None or htf_candles.empty:
        return True
    last = htf_candles.iloc[-1]
    ema20 = float(last.get("ema20", float("nan")))
    ema50 = float(last.get("ema50", float("nan")))
    if pd.isna(ema20) or pd.isna(ema50):
        return True
    if signal.side == "BUY":
        return ema20 > ema50
    return ema20 < ema50


class SignalService:
    """Produces candidate trading signals from strategies for a symbol."""

    def __init__(
        self,
        strategies: list[Strategy] | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Initialise the service.

        Args:
            strategies: Explicit strategy instances. When provided they are
                reused for every symbol (no per-symbol optimized params).
            settings: Settings instance (defaults to ``get_settings()``).
        """
        self._default_strategies: list[Strategy] | None = strategies
        self._settings = settings or get_settings()
        self._strategy_cache: dict[str, list[Strategy]] = {}

    @property
    def strategies(self) -> list[Strategy]:
        """Default strategy instances (no symbol-specific params applied)."""
        if self._default_strategies is not None:
            return self._default_strategies
        return [s() for s in ALL_STRATEGIES]

    def _strategies_for(self, symbol: str) -> list[Strategy]:
        """Return strategy instances for ``symbol``, loading optimized params once.

        Args:
            symbol: NSE trading symbol.

        Returns:
            Cached list of Strategy instances configured for ``symbol``.
        """
        if self._default_strategies is not None:
            return self._default_strategies

        if symbol not in self._strategy_cache:
            opt_params = load_params_for_symbol(symbol)
            instances: list[Strategy] = []
            for cls in ALL_STRATEGIES:
                params = opt_params.get(cls.name, {})
                try:
                    strat = cls(**params) if params else cls()
                    if params:
                        log.info(
                            "strategy_loaded_optimized_params",
                            symbol=symbol,
                            strategy=cls.name,
                            params=params,
                        )
                except TypeError as exc:
                    log.warning(
                        "strategy_optimized_params_invalid",
                        symbol=symbol,
                        strategy=cls.name,
                        error=str(exc),
                    )
                    strat = cls()
                instances.append(strat)
            self._strategy_cache[symbol] = instances

        return self._strategy_cache[symbol]

    def generate(
        self,
        symbol: str,
        candles: pd.DataFrame,
        htf_candles: pd.DataFrame | None = None,
    ) -> list[Signal]:
        """Generate signals for ``symbol`` through the enabled strategies.

        Applies two optional filters when the corresponding settings are on:
        1. Regime filter — strategy's ``preferred_regimes`` must contain the
           detected regime.
        2. HTF agreement — higher-timeframe EMA trend must align with the
           signal's side.

        Args:
            symbol: NSE trading symbol (e.g. ``"NIFTY"``).
            candles: Base-timeframe OHLCV frame with indicators.
            htf_candles: Higher-timeframe OHLCV frame with indicators
                (only used when ``require_htf_agreement`` is enabled).

        Returns:
            List of signals that passed all enabled filters (may be empty).
        """
        regime = detect_regime(candles)
        log.debug("regime_detected", symbol=symbol, regime=regime)

        signals: list[Signal] = []
        for strat in self._strategies_for(symbol):
            if self._settings.regime_filter_enabled and not strat.applies_to_regime(regime):
                log.debug(
                    "strategy_skipped_regime",
                    strategy=strat.name,
                    symbol=symbol,
                    regime=regime,
                )
                continue
            try:
                sig = strat.evaluate(symbol, candles)
            except Exception as e:  # strategies must not raise — log and continue
                log.warning("strategy_error", strategy=strat.name, symbol=symbol, error=str(e))
                continue
            if sig is None:
                continue
            if self._settings.require_htf_agreement and not _htf_agrees(sig, htf_candles):
                log.debug(
                    "signal_rejected_htf",
                    symbol=symbol,
                    strategy=strat.name,
                    side=sig.side,
                )
                continue
            signals.append(sig)

        return signals
