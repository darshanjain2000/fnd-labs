"""Risk Engine — THE most critical component.

Rules (all must pass before an order is placed):
  1. Kill switch is OFF.
  2. Per-trade risk <= MAX_RISK_PER_TRADE_PCT of capital.
  3. Today's realized loss has not breached MAX_DAILY_LOSS_PCT.
  4. Open positions count < MAX_OPEN_POSITIONS.
  5. Trades already placed today < MAX_TRADES_PER_DAY.
  6. Computed qty >= 1 and aligned to lot size (F&O).
  7. If expiry-day: block in final BLOCK_EXPIRY_LAST_HOURS.

Phase 3 addition:
  8. Optional half-Kelly multiplier on risk_pct (kelly_sizing_enabled).
    9. R:R gate: target/SL must be >= min_rr_ratio when rr_gate_enabled (default 2.0).

AI cannot override rejection. Approval still passes through this gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.market_calendar import minutes_to_close, now_ist
from app.strategies.base import Signal

log = get_logger(__name__)


@dataclass
class RiskDecision:
    """Outcome of a risk check.

    Attributes:
        approved: Whether the trade is permitted.
        qty: Computed position size (0 if rejected).
        reason: Machine-readable rejection reason or "ok".
    """

    approved: bool
    qty: int
    reason: str = ""


@dataclass
class DailyStats:
    """Intraday counters reset at midnight IST."""

    trades_today: int = 0
    realized_pnl_today: float = 0.0
    open_positions: int = 0
    last_reset: date = date.today()


def position_size(capital: float, risk_pct: float, entry: float, stop: float, lot_size: int = 1) -> int:
    """Compute risk-based position size rounded DOWN to a lot-size multiple.

    Args:
        capital: Total capital in INR.
        risk_pct: Maximum percentage of capital to risk on this trade.
        entry: Entry price.
        stop: Stop-loss price.
        lot_size: F&O lot size (position must be a multiple of this).

    Returns:
        Number of units to trade (0 if risk per unit is zero/negative).
    """
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return 0
    risk_budget = capital * (risk_pct / 100.0)
    raw_qty = risk_budget / risk_per_unit
    lots = int(raw_qty // lot_size)
    return lots * lot_size


def compute_kelly_fraction(pnl_history: list[float]) -> float:
    """Compute a half-Kelly multiplier from a list of closed-trade PnLs.

    Uses the classic Kelly formula: ``f = W - (1-W)/B``, where W is win-rate
    and B is average-win / average-loss, then halves it (conservative half-Kelly).
    Result is clamped to ``[0.25, 1.0]``.

    Args:
        pnl_history: List of realised PnL values (positive = win, negative = loss).
            At least 5 values are required; fewer returns 1.0 (no adjustment).

    Returns:
        Kelly fraction in [0.25, 1.0]. Returns 1.0 when data is insufficient.
    """
    if len(pnl_history) < 5:
        return 1.0
    wins = [p for p in pnl_history if p > 0]
    losses = [p for p in pnl_history if p <= 0]
    if not wins or not losses:
        return 1.0
    win_rate = len(wins) / len(pnl_history)
    avg_win = sum(wins) / len(wins)
    avg_loss = abs(sum(losses) / len(losses))
    if avg_loss == 0:
        return 1.0
    b = avg_win / avg_loss
    kelly = win_rate - (1.0 - win_rate) / b
    return max(0.25, min(1.0, kelly / 2.0))  # half-Kelly, bounded


class RiskEngine:
    """Evaluates trade signals against all risk gates before execution."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialise with optional Settings override (useful in tests).

        Args:
            settings: Settings instance. Defaults to ``get_settings()``.
        """
        self.s = settings or get_settings()
        self.stats = DailyStats()
        self._kelly_fraction: float = 1.0  # updated by update_kelly_fraction()

    def _maybe_reset_day(self, at: datetime) -> None:
        """Reset daily stats if the date has rolled over.

        Args:
            at: Current IST datetime.
        """
        if at.date() != self.stats.last_reset:
            log.info("risk_daily_reset", prev=self.stats.__dict__)
            self.stats = DailyStats(last_reset=at.date())

    def update_kelly_fraction(self, pnl_history: list[float]) -> None:
        """Recompute and store the Kelly position-sizing multiplier.

        Designed to be called once per scheduler tick (or once per day) with
        the most recent N closed-trade PnLs. No-ops when Kelly sizing is
        disabled in settings.

        Args:
            pnl_history: Recent closed-trade PnL values (INR).
        """
        if not self.s.kelly_sizing_enabled:
            return
        self._kelly_fraction = compute_kelly_fraction(pnl_history)
        log.debug("kelly_fraction_updated", fraction=self._kelly_fraction)

    def record_trade_open(self) -> None:
        """Increment open-position and daily-trade counters."""
        self.stats.trades_today += 1
        self.stats.open_positions += 1

    def record_trade_close(self, pnl: float) -> None:
        """Decrement open-position counter and accumulate daily PnL.

        Args:
            pnl: Realised PnL in INR for the closed trade.
        """
        self.stats.open_positions = max(0, self.stats.open_positions - 1)
        self.stats.realized_pnl_today += pnl

    def evaluate(self, signal: Signal, lot_size: int = 1, is_expiry_day: bool = False) -> RiskDecision:
        """Run all risk gates and return a RiskDecision.

        Args:
            signal: The trading signal to evaluate.
            lot_size: F&O lot size for position sizing.
            is_expiry_day: Whether today is the contract expiry day.

        Returns:
            RiskDecision with approved flag, qty, and rejection reason.
        """
        at = now_ist()
        self._maybe_reset_day(at)
        s = self.s

        if s.kill_switch:
            return RiskDecision(False, 0, "kill_switch_on")

        if self.stats.trades_today >= s.max_trades_per_day:
            return RiskDecision(False, 0, "max_trades_per_day")

        if self.stats.open_positions >= s.max_open_positions:
            return RiskDecision(False, 0, "max_open_positions")

        daily_loss_cap = -s.capital_inr * (s.max_daily_loss_pct / 100.0)
        if self.stats.realized_pnl_today <= daily_loss_cap:
            return RiskDecision(False, 0, "daily_loss_limit")

        if is_expiry_day and minutes_to_close(at) <= s.block_expiry_last_hours * 60:
            return RiskDecision(False, 0, "expiry_day_last_hours_block")

        effective_risk_pct = s.max_risk_per_trade_pct * self._kelly_fraction
        qty = position_size(s.capital_inr, effective_risk_pct, signal.entry, signal.stop_loss, lot_size)
        if qty < 1:
            return RiskDecision(False, 0, "qty_below_lot_size")

        risk_amount = abs(signal.entry - signal.stop_loss) * qty
        max_risk = s.capital_inr * (s.max_risk_per_trade_pct / 100.0)
        if risk_amount > max_risk * 1.0001:
            return RiskDecision(False, 0, "risk_exceeds_cap")

        if s.rr_gate_enabled and signal.target is not None:
            reward = abs(signal.target - signal.entry)
            risk_per_unit = abs(signal.entry - signal.stop_loss)
            if risk_per_unit > 0 and reward / risk_per_unit < s.min_rr_ratio:
                return RiskDecision(False, 0, "rr_below_minimum")

        return RiskDecision(True, qty, "ok")
