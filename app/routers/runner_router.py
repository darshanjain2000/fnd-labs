"""Scheduler start/stop/status endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app.models.api import ApiResponse, RunnerStartOut, RunnerStatusOut, RunnerStopOut
from app.services.scheduler import MarketScheduler, get_scheduler

router = APIRouter(prefix="/runner", tags=["runner"])


def _status_dto(sched: MarketScheduler) -> RunnerStatusOut:
    """Convert the scheduler's mutable status dataclass into a DTO."""
    s = sched.status
    return RunnerStatusOut(
        running=s.running,
        started_at=s.started_at,
        last_tick_at=s.last_tick_at,
        ticks=s.ticks,
        signals_seen=s.signals_seen,
        trades_opened=s.trades_opened,
        trades_auto_closed=s.trades_auto_closed,
        last_error=s.last_error,
        watchlist=list(s.watchlist),
    )


@router.post("/start", response_model=ApiResponse[RunnerStartOut])
def start_runner() -> ApiResponse[RunnerStartOut]:
    """Start the intraday runner if not already running."""
    sched = get_scheduler()
    started = sched.start()
    return ApiResponse[RunnerStartOut].ok(
        RunnerStartOut(started=started, already_running=not started)
    )


@router.post("/stop", response_model=ApiResponse[RunnerStopOut])
async def stop_runner() -> ApiResponse[RunnerStopOut]:
    """Stop the intraday runner and return its final status snapshot."""
    sched = get_scheduler()
    await sched.stop()
    return ApiResponse[RunnerStopOut].ok(
        RunnerStopOut(stopped=True, status=_status_dto(sched))
    )


@router.get("/status", response_model=ApiResponse[RunnerStatusOut])
def runner_status() -> ApiResponse[RunnerStatusOut]:
    """Return the live scheduler status snapshot."""
    return ApiResponse[RunnerStatusOut].ok(_status_dto(get_scheduler()))
