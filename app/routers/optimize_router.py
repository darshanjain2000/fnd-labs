"""Optimization runner — launch Optuna jobs and stream progress via SSE.

Flow:
    POST /optimize/run   → spawns optimize_all.py as a subprocess, returns job_id
    GET  /optimize/stream/{job_id} → SSE stream of stdout lines (one per data event)
    GET  /optimize/status/{job_id} → polling fallback: job state + line count
    GET  /optimize/results/{symbol} → parsed YAML best-params for a symbol
"""

from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.core.logging import get_logger
from app.models.api.response import ApiResponse

log = get_logger(__name__)

router = APIRouter(prefix="/optimize", tags=["optimize"])

# Path to the repo root (two levels above app/routers/)
_REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_JOB_STORE_PATH: Path = _REPO_ROOT / "logs" / "optimize_jobs.json"
_JOB_LOCK = threading.Lock()

# In-memory job store.  Keys are job UUIDs; values are mutable state dicts.
# Not persisted — jobs disappear on server restart.
_JOBS: dict[str, dict[str, Any]] = {}


def _persist_jobs() -> None:
    """Persist job metadata to disk so history survives API restarts."""
    _JOB_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: list[dict[str, Any]] = []
    with _JOB_LOCK:
        for job in _JOBS.values():
            payload.append(
                {
                    "job_id": job.get("job_id"),
                    "symbol": job.get("symbol"),
                    "status": job.get("status"),
                    "returncode": job.get("returncode"),
                    "lines": job.get("lines", [])[-500:],
                    "created_at": job.get("created_at"),
                    "finished_at": job.get("finished_at"),
                }
            )
    _JOB_STORE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_jobs() -> None:
    """Hydrate job history from disk at import time.

    Any job that was ``running`` before restart is marked ``interrupted``.
    """
    if not _JOB_STORE_PATH.exists():
        return
    try:
        raw = json.loads(_JOB_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    for row in raw if isinstance(raw, list) else []:
        job_id = str(row.get("job_id") or "")
        if not job_id:
            continue
        status = str(row.get("status") or "unknown")
        if status == "running":
            status = "interrupted"
        _JOBS[job_id] = {
            "job_id": job_id,
            "symbol": row.get("symbol"),
            "status": status,
            "lines": row.get("lines", []),
            "returncode": row.get("returncode"),
            "created_at": row.get("created_at"),
            "finished_at": row.get("finished_at"),
            "proc": None,
            "queue": queue.Queue(),
        }


class OptimizeRequest(BaseModel):
    """Parameters for a new optimization run."""

    symbol: str
    from_date: str = "2024-01-01"
    to_date: str = Field(default="")
    trials: int = Field(default=100, ge=1, le=1000)
    interval: str = "5m"
    metric: str = "sortino"

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        """Normalise symbol to uppercase."""
        return v.upper().strip()

    @field_validator("metric")
    @classmethod
    def _valid_metric(cls, v: str) -> str:
        """Validate metric is one of the known choices."""
        allowed = {"sortino", "sharpe", "win_rate"}
        if v not in allowed:
            raise ValueError(f"metric must be one of {allowed}")
        return v


def _reader_thread(
    proc: subprocess.Popen[str],
    line_queue: queue.Queue[str | None],
) -> None:
    """Background thread: read subprocess stdout and push lines to queue.

    Pushes ``None`` as a sentinel when the process terminates.

    Args:
        proc: The running subprocess.
        line_queue: Thread-safe queue shared with the async SSE generator.
    """
    assert proc.stdout is not None
    for raw in proc.stdout:
        line_queue.put(raw.rstrip("\n"))
    line_queue.put(None)  # sentinel: subprocess finished


@router.post("/run", response_model=ApiResponse[dict])
def start_optimize(req: OptimizeRequest) -> ApiResponse[dict]:
    """Launch a background Optuna optimization job for a symbol.

    Runs ``optimize_all.py`` as a subprocess so the FastAPI process stays
    responsive. Returns a ``job_id`` UUID to track progress via SSE.

    Args:
        req: Optimization parameters (symbol, date range, trials, metric).

    Returns:
        ApiResponse with ``job_id`` and ``started`` flag.
    """
    to_date = req.to_date or str(date.today())
    job_id = str(uuid.uuid4())

    cmd: list[str] = [
        sys.executable,
        str(_REPO_ROOT / "optimize_all.py"),
        "--symbol",
        req.symbol,
        "--from",
        req.from_date,
        "--to",
        to_date,
        "--trials",
        str(req.trials),
        "--interval",
        req.interval,
        "--metric",
        req.metric,
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(_REPO_ROOT),
        )
    except Exception as e:
        log.error("optimize_launch_failed", symbol=req.symbol, error=str(e))
        return ApiResponse[dict].ok({"started": False, "error": str(e)})

    line_q: queue.Queue[str | None] = queue.Queue()
    _JOBS[job_id] = {
        "job_id": job_id,
        "symbol": req.symbol,
        "status": "running",
        "lines": [],
        "returncode": None,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "finished_at": None,
        "proc": proc,
        "queue": line_q,
    }
    _persist_jobs()

    t = threading.Thread(target=_reader_thread, args=(proc, line_q), daemon=True)
    t.start()

    log.info(
        "optimize_job_started", job_id=job_id, symbol=req.symbol, trials=req.trials
    )
    return ApiResponse[dict].ok(
        {"started": True, "job_id": job_id, "symbol": req.symbol, "cmd": " ".join(cmd)}
    )


@router.get("/status/{job_id}", response_model=ApiResponse[dict])
def job_status(job_id: str) -> ApiResponse[dict]:
    """Return the current state of an optimization job.

    Args:
        job_id: UUID returned by ``POST /optimize/run``.

    Returns:
        ApiResponse with ``status`` (running / done / failed / not_found),
        ``lines_count``, and ``returncode``.
    """
    job = _JOBS.get(job_id)
    if job is None:
        return ApiResponse[dict].ok({"status": "not_found", "job_id": job_id})
    return ApiResponse[dict].ok(
        {
            "job_id": job_id,
            "symbol": job["symbol"],
            "status": job["status"],
            "lines_count": len(job["lines"]),
            "returncode": job["returncode"],
            "created_at": job.get("created_at"),
            "finished_at": job.get("finished_at"),
        }
    )


@router.get("/jobs", response_model=ApiResponse[dict])
def list_jobs(limit: int = 30) -> ApiResponse[dict]:
    """Return recent optimization jobs (newest first)."""
    rows = sorted(
        _JOBS.values(),
        key=lambda j: (j.get("created_at") or "", j.get("job_id") or ""),
        reverse=True,
    )
    out = [
        {
            "job_id": r.get("job_id"),
            "symbol": r.get("symbol"),
            "status": r.get("status"),
            "returncode": r.get("returncode"),
            "created_at": r.get("created_at"),
            "finished_at": r.get("finished_at"),
        }
        for r in rows[: max(1, min(limit, 200))]
    ]
    return ApiResponse[dict].ok({"jobs": out, "count": len(out)})


@router.post("/cancel/{job_id}", response_model=ApiResponse[dict])
def cancel_job(job_id: str) -> ApiResponse[dict]:
    """Cancel a running optimization job.

    Args:
        job_id: UUID returned by ``POST /optimize/run``.

    Returns:
        ApiResponse describing whether cancellation was applied.
    """
    job = _JOBS.get(job_id)
    if job is None:
        return ApiResponse[dict].ok(
            {"cancelled": False, "reason": "not_found", "job_id": job_id}
        )

    if job.get("status") != "running":
        return ApiResponse[dict].ok(
            {
                "cancelled": False,
                "reason": "not_running",
                "job_id": job_id,
                "status": job.get("status"),
            }
        )

    proc: subprocess.Popen[str] | None = job.get("proc")
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception as e:
            return ApiResponse[dict].ok(
                {
                    "cancelled": False,
                    "reason": "terminate_failed",
                    "error": str(e),
                    "job_id": job_id,
                }
            )

    job["status"] = "cancelled"
    job["returncode"] = -15
    job["finished_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    job["lines"].append("[cancelled by user]")
    q: queue.Queue[str | None] = job.get("queue")
    if q is not None:
        q.put(None)
    _persist_jobs()
    log.info("optimize_job_cancelled", job_id=job_id, symbol=job.get("symbol"))
    return ApiResponse[dict].ok({"cancelled": True, "job_id": job_id})


@router.get("/stream/{job_id}")
async def stream_optimize(job_id: str) -> StreamingResponse:
    """SSE endpoint — stream optimization log lines as the subprocess produces them.

    Each SSE event is a single log line from ``optimize_all.py`` stdout.
    When the process finishes, a final ``__DONE__ returncode=N`` event is emitted.
    Clients that reconnect receive all previously captured lines first (replay).

    Args:
        job_id: UUID returned by ``POST /optimize/run``.

    Returns:
        A ``text/event-stream`` streaming response.
    """
    job = _JOBS.get(job_id)
    if job is None:

        async def _not_found() -> Any:
            yield 'data: {"error": "job not found"}\n\n'

        return StreamingResponse(_not_found(), media_type="text/event-stream")

    async def _generate() -> Any:
        line_q: queue.Queue[str | None] = job["queue"]
        sent_idx = 0
        loop = asyncio.get_event_loop()

        # Replay lines already captured (handles browser reconnect)
        while sent_idx < len(job["lines"]):
            yield f"data: {job['lines'][sent_idx]}\n\n"
            sent_idx += 1

        if job["status"] != "running":
            yield f"data: __DONE__ returncode={job['returncode']}\n\n"
            return

        # Stream new lines from subprocess via the thread-safe queue
        while True:
            try:
                line: str | None = await loop.run_in_executor(
                    None, lambda: line_q.get(timeout=1.0)
                )
            except queue.Empty:
                yield ": keepalive\n\n"
                continue

            if line is None:
                # Subprocess finished
                proc: subprocess.Popen[str] = job["proc"]
                rc = (
                    proc.returncode
                    if (proc and proc.returncode is not None)
                    else (proc.wait() if proc else -1)
                )
                if job.get("status") == "running":
                    job["status"] = "done" if rc == 0 else "failed"
                    job["returncode"] = rc
                    job["finished_at"] = (
                        datetime.utcnow().isoformat(timespec="seconds") + "Z"
                    )
                _persist_jobs()
                yield f"data: __DONE__ returncode={job.get('returncode')} status={job.get('status')}\n\n"
                break

            job["lines"].append(line)
            if len(job["lines"]) % 25 == 0:
                _persist_jobs()
            yield f"data: {line}\n\n"
            sent_idx += 1

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/results/{symbol}", response_model=ApiResponse[dict])
def optimization_results(symbol: str) -> ApiResponse[dict]:
    """Return the Optuna-optimized params YAML for a symbol as structured JSON.

    Args:
        symbol: Trading symbol (case-insensitive).

    Returns:
        ApiResponse with a ``params`` dict (strategy name → best params + metrics).
    """
    path = _REPO_ROOT / "config" / f"params_{symbol.lower()}.yaml"
    if not path.exists():
        return ApiResponse[dict].ok({"symbol": symbol.upper(), "params": {}})
    data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    return ApiResponse[dict].ok({"symbol": symbol.upper(), "params": data})


_load_jobs()
