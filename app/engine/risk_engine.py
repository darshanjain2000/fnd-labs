"""Risk Engine — THE most critical component.

Rules (all must pass before an order is placed):
  1. Kill switch is OFF.
  2. Per-trade risk <= MAX_RISK_PER_TRADE_PCT of capital.
  3. Today's realized loss has not breached MAX_DAILY_LOSS_PCT.
  4. Open positions count < MAX_OPEN_POSITIONS.
  5. Trades already placed today < MAX_TRADES_PER_DAY.
  6. Computed qty >= 1 and aligned to lot size (F&O).
  7. If expiry-day: block in final BLOCK_EXPIRY_LAST_HOURS.

AI cannot override rejection. Approval still passes through this gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from config import Settings, get_settings
from core.logging import get_logger
from core.market_calendar import minutes_to_close, now_ist
from strategies.base import Signal

log = get_logger(__name__)


@dataclass
class RiskDecision:
    approved: bool
    qty: int
    reason: str = ""


@dataclass
class DailyStats:
    trades_today: int = 0
    realized_pnl_today: float = 0.0
    open_positions: int = 0
    last_reset: date = date.today()


def position_size(capital: float, risk_pct: float, entry: float, stop: float, lot_size: int = 1) -> int:
    """Risk-based position sizing, rounded DOWN to a lot size multiple."""
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return 0
    risk_budget = capital * (risk_pct / 100.0)
    raw_qty = risk_budget / risk_per_unit
    lots = int(raw_qty // lot_size)
    return lots * lot_size


class RiskEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()
        self.stats = DailyStats()

    def _maybe_reset_day(self, at: datetime) -> None:
        if at.date() != self.stats.last_reset:
            log.info("risk_daily_reset", prev=self.stats.__dict__)
            self.stats = DailyStats(last_reset=at.date())

    def record_trade_open(self) -> None:
        self.stats.trades_today += 1
        self.stats.open_positions += 1

    def record_trade_close(self, pnl: float) -> None:
        self.stats.open_positions = max(0, self.stats.open_positions - 1)
        self.stats.realized_pnl_today += pnl

    def evaluate(self, signal: Signal, lot_size: int = 1, is_expiry_day: bool = False) -> RiskDecision:
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

        qty = position_size(s.capital_inr, s.max_risk_per_trade_pct, signal.entry, signal.stop_loss, lot_size)
        if qty < 1:
            return RiskDecision(False, 0, "qty_below_lot_size")

        risk_amount = abs(signal.entry - signal.stop_loss) * qty
        max_risk = s.capital_inr * (s.max_risk_per_trade_pct / 100.0)
        if risk_amount > max_risk * 1.0001:
            return RiskDecision(False, 0, "risk_exceeds_cap")

        return RiskDecision(True, qty, "ok")
