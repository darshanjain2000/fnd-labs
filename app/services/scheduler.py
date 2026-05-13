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
from datetime import datetime
from zoneinfo import ZoneInfo

from app.routers.deps import get_orchestrator, set_mock_quote
from app.config import get_settings
from app.core.logging import get_logger
from app.core.market_calendar import is_market_open, next_market_open, parse_hhmm
from app.services.angel_session import get_angel_session
from app.services.market_data import compute_indicators

log = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")


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
        self._last_heartbeat_at: datetime | None = None  # throttle heartbeat log

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
        return is_market_open(
            now,
            market_open=parse_hhmm(s.market_open),
            market_close=parse_hhmm(s.market_close),
        )

    def _past_square_off(self, now: datetime) -> bool:
        s = get_settings()
        return now.time() >= parse_hhmm(s.square_off_time)

    def _describe_next_open(self, now: datetime) -> str:
        """Return a human-readable string like 'Mon 20 Apr 09:15 IST (in 15h 42m)'."""
        market_open = parse_hhmm(get_settings().market_open)
        candidate = next_market_open(now, market_open=market_open)
        delta = candidate - now
        hrs = int(delta.total_seconds() // 3600)
        mins = int((delta.total_seconds() % 3600) // 60)
        return f"{candidate.strftime('%a %d %b %H:%M IST')} (in {hrs}h {mins}m)"

    def _maybe_log_heartbeat(self, now: datetime) -> None:
        """Emit a live-status log if the configured heartbeat interval has elapsed.

        Reads LOG_HEARTBEAT_INTERVAL_SEC from settings. Set to 0 to disable.
        Pulls open-position and P&L stats from the risk engine singleton so the
        heartbeat line shows a meaningful snapshot without touching the DB.

        Args:
            now: Current IST datetime (injected so tests can control it).
        """
        interval = get_settings().log_heartbeat_interval_sec
        if interval <= 0:
            return
        if (
            self._last_heartbeat_at is not None
            and (now - self._last_heartbeat_at).total_seconds() < interval
        ):
            return

        self._last_heartbeat_at = now
        risk_stats = get_orchestrator().risk.stats
        uptime_sec = (
            int((now - self.status.started_at).total_seconds())
            if self.status.started_at
            else 0
        )
        hrs, rem = divmod(uptime_sec, 3600)
        mins = rem // 60
        log.info(
            "scheduler_heartbeat",
            tick=self.status.ticks,
            open_positions=risk_stats.open_positions,
            trades_today=risk_stats.trades_today,
            realized_pnl=risk_stats.realized_pnl_today,
            signals_seen=self.status.signals_seen,
            uptime=f"{hrs}h {mins}m",
        )

    def _emit_eod_summary(
        self, closed_in_square_off: int, now: datetime
    ) -> dict[str, object]:
        """Build and log a one-line EOD summary snapshot.

        Args:
            closed_in_square_off: Count of positions force-closed at EOD.
            now: Current IST timestamp.

        Returns:
            A JSON-safe summary payload.
        """
        risk_stats = get_orchestrator().risk.stats
        payload: dict[str, object] = {
            "date_ist": now.strftime("%Y-%m-%d"),
            "ticks": self.status.ticks,
            "signals_seen": self.status.signals_seen,
            "trades_opened": self.status.trades_opened,
            "trades_auto_closed": self.status.trades_auto_closed,
            "closed_in_square_off": closed_in_square_off,
            "realized_pnl": round(float(risk_stats.realized_pnl_today), 2),
            "open_positions": int(risk_stats.open_positions),
            "trades_today": int(risk_stats.trades_today),
        }
        log.info("scheduler_eod_summary", **payload)
        return payload

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

        # Pre-warm the Angel session in a single thread before parallel fetch.
        # This ensures all parallel candle requests start from an already-logged-in
        # session, preventing a login race where all threads fire simultaneously.
        await asyncio.to_thread(session.ensure_ready)

        # Parallel candle fetch — staggered + concurrency-capped to avoid Angel One rate limiting.
        # Stagger spreads request start times; semaphore ensures at most fetch_max_concurrent
        # requests are in-flight at any moment, regardless of stagger timing.
        fetch_started = datetime.now(IST)
        stagger_sec = s.fetch_stagger_ms / 1000.0
        sem = asyncio.Semaphore(s.fetch_max_concurrent)
        if stagger_sec > 0:
            log.debug(
                "scheduler_fetch_staggered",
                symbols=len(pairs),
                stagger_ms=s.fetch_stagger_ms,
            )

        async def _fetch_one(sym: str, exch: str, index: int) -> tuple:
            """Fetch candles for one symbol with stagger delay and concurrency cap."""
            if stagger_sec > 0 and index > 0:
                await asyncio.sleep(index * stagger_sec)
            async with sem:
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
            *[_fetch_one(sym, exch, i) for i, (sym, exch) in enumerate(pairs)],
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
        closed = orch.execution_agent.mark_to_market(
            latest_prices, reason_tag="live_tick"
        )
        self.status.trades_auto_closed += len(closed)
        # Broadcast mark-to-market closes
        from app.services.ws_broadcaster import get_broadcaster

        broadcaster = get_broadcaster()
        for t in closed:
            asyncio.create_task(
                broadcaster.publish(
                    "trade_closed",
                    {
                        "id": t.id,
                        "symbol": t.symbol,
                        "pnl": t.pnl,
                        "exit_price": t.exit_price,
                        "reason": "sl_or_target",
                    },
                )
            )
        # Broadcast latest prices snapshot
        if latest_prices:
            asyncio.create_task(
                broadcaster.publish("mtm_update", {"prices": latest_prices})
            )

        # 2. Square-off at EOD
        today_key = now_ist.strftime("%Y-%m-%d")
        if self._past_square_off(now_ist) and self._squared_off_on != today_key:
            forced = orch.execution_agent.force_close_all(
                latest_prices, reason="eod_square_off"
            )
            self._squared_off_on = today_key
            log.info("scheduler_eod_square_off", closed=len(forced))
            summary = self._emit_eod_summary(
                closed_in_square_off=len(forced), now=now_ist
            )
            asyncio.create_task(broadcaster.publish("eod_summary", summary))
            return  # don't open new trades after square-off time

        # 3. Generate & execute new signals per symbol (skip if already in a trade)
        from app.dal.trade_dal import TradeDAL

        symbols_in_trade = set(TradeDAL().list_open_symbols())
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
            # Broadcast each outcome
            for outcome in outcomes:
                sig = outcome.signal or {}
                if outcome.executed:
                    asyncio.create_task(
                        broadcaster.publish(
                            "trade_opened",
                            {
                                "id": outcome.trade_id,
                                "symbol": sym,
                                "side": sig.get("side"),
                                "strategy": sig.get("strategy"),
                                "entry_price": outcome.fill_price,
                                "stop_loss": sig.get("stop_loss"),
                                "target": sig.get("target"),
                                "qty": outcome.qty,
                                "confidence": sig.get("confidence"),
                            },
                        )
                    )
                else:
                    asyncio.create_task(
                        broadcaster.publish(
                            "signal_generated",
                            {
                                "symbol": sym,
                                "strategy": sig.get("strategy"),
                                "side": sig.get("side"),
                                "confidence": sig.get("confidence"),
                                "ai_approved": outcome.ai_approved,
                                "risk_approved": outcome.risk_approved,
                                "risk_reason": outcome.risk_reason,
                            },
                        )
                    )

        log.info(
            "scheduler_tick_done",
            symbols=len(candle_dfs),
            skipped=skipped,
            closed=len(closed),
            total_ticks=self.status.ticks,
        )
        self._maybe_log_heartbeat(now_ist)
        # Broadcast tick summary to all WebSocket clients
        asyncio.create_task(
            broadcaster.publish(
                "tick_summary",
                {
                    "tick": self.status.ticks,
                    "symbols_fetched": len(candle_dfs),
                    "skipped": skipped,
                    "mtm_closed": len(closed),
                    "signals_seen": self.status.signals_seen,
                    "trades_opened": self.status.trades_opened,
                    "timestamp": now_ist.isoformat(),
                },
            )
        )


# ---- module-level singleton ----------------------------------------------
_scheduler: MarketScheduler | None = None


def get_scheduler() -> MarketScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = MarketScheduler()
    return _scheduler
