"""Intraday live-data paper-trading scheduler.

Responsibilities
----------------
1. During market hours (IST 09:15-15:30 by default), every RUN_INTERVAL_SEC:
     - For each watchlist symbol, fetch fresh candles from Angel One
     - Mark-to-market OPEN trades: close any whose SL/target was breached
     - Run the orchestrator pipeline (strategy → AI → risk → execution)
2. At SQUARE_OFF_TIME, force-close all remaining OPEN trades (EOD flatten).
3. Exposes start()/stop()/status() for the runner API.

No threads — uses asyncio background task (FastAPI-friendly).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from app.api.deps import get_orchestrator, set_mock_quote
from app.config import get_settings
from app.core.logging import get_logger
from app.services.angel_session import get_angel_session
from app.services.market_data import compute_indicators

log = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")


def _parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


@dataclass
class SchedulerStatus:
    running: bool = False
    started_at: datetime | None = None
    last_tick_at: datetime | None = None
    ticks: int = 0
    signals_seen: int = 0
    trades_opened: int = 0
    trades_auto_closed: int = 0
    last_error: str | None = None
    watchlist: list[str] = field(default_factory=list)


class MarketScheduler:
    """Runs the intraday loop as an asyncio task."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self.status = SchedulerStatus()
        self._squared_off_on: str | None = None  # "YYYY-MM-DD" of last square-off
        self._last_idle_log_min: int = -1  # throttle "market closed" log to once/min

    # ---- public API ------------------------------------------------------
    def start(self) -> bool:
        if self._task and not self._task.done():
            return False
        self._stop_event.clear()
        self.status = SchedulerStatus(
            running=True,
            started_at=datetime.now(IST),
            watchlist=[f"{s}:{e}" for s, e in get_settings().watchlist_pairs()],
        )
        self._task = asyncio.create_task(self._loop(), name="market_scheduler")
        log.info("scheduler_started", watchlist=self.status.watchlist)
        return True

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        self.status.running = False
        log.info("scheduler_stopped", ticks=self.status.ticks)

    # ---- internals -------------------------------------------------------
    def _within_market_hours(self, now: datetime) -> bool:
        s = get_settings()
        if now.weekday() >= 5:  # Sat / Sun
            return False
        open_t = _parse_hhmm(s.market_open)
        close_t = _parse_hhmm(s.market_close)
        return open_t <= now.time() <= close_t

    def _past_square_off(self, now: datetime) -> bool:
        s = get_settings()
        return now.time() >= _parse_hhmm(s.square_off_time)

    def _describe_next_open(self, now: datetime) -> str:
        """Return a human-readable string like 'Mon 20 Apr 09:15 IST (in 15h 42m)'."""
        s = get_settings()
        open_t = _parse_hhmm(s.market_open)
        candidate = now.replace(hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0)
        # If today's open already passed OR today is weekend, roll forward
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        while candidate.weekday() >= 5:  # Sat / Sun
            candidate = candidate + timedelta(days=1)
        delta = candidate - now
        hrs = int(delta.total_seconds() // 3600)
        mins = int((delta.total_seconds() % 3600) // 60)
        return f"{candidate.strftime('%a %d %b %H:%M IST')} (in {hrs}h {mins}m)"

    async def _loop(self) -> None:
        log.info("scheduler_loop_entry")
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception as e:  # pragma: no cover — never die silently
                self.status.last_error = f"{type(e).__name__}: {e}"
                log.exception("scheduler_tick_failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=get_settings().run_interval_sec,
                )
            except asyncio.TimeoutError:
                continue  # normal — fire next tick

    async def _tick(self) -> None:
        s = get_settings()
        now_ist = datetime.now(IST)
        self.status.last_tick_at = now_ist
        self.status.ticks += 1

        if not self._within_market_hours(now_ist):
            # Only log once per minute to avoid spam while waiting
            cur_min = now_ist.hour * 60 + now_ist.minute
            if cur_min != self._last_idle_log_min:
                self._last_idle_log_min = cur_min
                next_open_msg = self._describe_next_open(now_ist)
                log.info(
                    "scheduler_outside_hours",
                    now=now_ist.strftime("%a %Y-%m-%d %H:%M:%S IST"),
                    next_open=next_open_msg,
                )
            today_key = now_ist.strftime("%Y-%m-%d")
            if self._squared_off_on and self._squared_off_on != today_key:
                self._squared_off_on = None
            return

        pairs = s.watchlist_pairs()
        if not pairs:
            log.warning("scheduler_tick_no_watchlist")
            return

        log.info(
            "scheduler_tick_start",
            tick=self.status.ticks,
            watchlist=[f"{sym}:{exch}" for sym, exch in pairs],
        )

        session = get_angel_session()
        latest_prices: dict[str, float] = {}
        candle_dfs: dict[str, tuple[str, object]] = {}  # symbol -> (exchange, df)

        # Parallel candle fetch — one bad symbol shouldn't kill the tick.
        fetch_started = datetime.now(IST)

        async def _fetch_one(sym: str, exch: str):
            try:
                df = await asyncio.to_thread(
                    session.fetch_candles_for_symbol,
                    sym,
                    exch,
                    s.run_candle_interval,
                    None,
                    None,
                )
                return sym, exch, df, None
            except Exception as e:
                return sym, exch, None, e

        results = await asyncio.gather(
            *[_fetch_one(sym, exch) for sym, exch in pairs],
            return_exceptions=False,
        )
        for sym, exch, df, err in results:
            if err is not None:
                log.warning("scheduler_fetch_failed", symbol=sym, error=str(err))
                continue
            if df is None or len(df) < 20:
                rows = 0 if df is None else len(df)
                log.warning("scheduler_too_few_candles", symbol=sym, rows=rows)
                continue
            latest_prices[sym] = float(df["close"].iloc[-1])
            candle_dfs[sym] = (exch, df)

        fetch_ms = int((datetime.now(IST) - fetch_started).total_seconds() * 1000)
        log.info(
            "scheduler_fetch_done",
            fetched=len(candle_dfs),
            requested=len(pairs),
            elapsed_ms=fetch_ms,
        )

        # 1. Mark-to-market: close any trades that hit SL/target
        orch = get_orchestrator()
        closed = orch.execution_agent.mark_to_market(latest_prices, reason_tag="live_tick")
        self.status.trades_auto_closed += len(closed)

        # 2. Square-off at EOD
        today_key = now_ist.strftime("%Y-%m-%d")
        if self._past_square_off(now_ist) and self._squared_off_on != today_key:
            forced = orch.execution_agent.force_close_all(latest_prices, reason="eod_square_off")
            self._squared_off_on = today_key
            log.info("scheduler_eod_square_off", closed=len(forced))
            return  # don't open new trades after square-off time

        # 3. Generate & execute new signals per symbol (skip if already in a trade)
        from app.db import SessionLocal
        from app.models.trade import Trade
        with SessionLocal() as db:
            symbols_in_trade = {
                r[0] for r in db.query(Trade.symbol).filter(Trade.status == "OPEN").all()
            }
        skipped = 0
        for sym, (_exch, df) in candle_dfs.items():
            if sym in symbols_in_trade:
                skipped += 1
                log.debug("scheduler_skip_in_trade", symbol=sym)
                continue
            set_mock_quote(sym, latest_prices[sym])
            df_ind = compute_indicators(df)
            outcomes = orch.run(sym, df_ind)
            self.status.signals_seen += len(outcomes)
            self.status.trades_opened += sum(1 for o in outcomes if o.executed)

        log.info(
            "scheduler_tick_done",
            symbols=len(candle_dfs),
            skipped=skipped,
            closed=len(closed),
            total_ticks=self.status.ticks,
        )


# ---- module-level singleton ----------------------------------------------
_scheduler: MarketScheduler | None = None


def get_scheduler() -> MarketScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = MarketScheduler()
    return _scheduler
