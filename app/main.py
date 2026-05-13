from __future__ import annotations

import os
from contextlib import asynccontextmanager

# When launched as a script (`python app/main.py` from the VS Code debugger),
# the project root isn't on sys.path, so `from app.*` imports fail. Fix it up.
if __name__ == "__main__" or __package__ in (None, ""):
    import sys
    from pathlib import Path

    _ROOT = Path(__file__).resolve().parent.parent
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db import init_db
from app.exceptions.base import DomainException
from app.models.api.response import ApiResponse
from app.routers.admin_router import router as admin_router
from app.routers.analyze_router import router as analyze_router
from app.routers.audit_router import router as audit_router
from app.routers.config_router import router as config_router
from app.routers.report_router import router as report_router
from app.routers.runner_router import router as runner_router
from app.routers.signals_router import router as signals_router
from app.routers.trade_router import router as trade_router
from app.routers.trades_router import router as trades_router
from app.routers.optimize_router import router as optimize_router
from app.routers.ops_router import router as ops_router
from app.routers.watchlist_router import router as watchlist_router
from app.routers.ws_router import router as ws_router
from app.services.scheduler import get_scheduler

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    s = get_settings()
    if s.auto_run_enabled:
        get_scheduler().start()
    yield
    sched = get_scheduler()
    if sched.status.running:
        await sched.stop()


app = FastAPI(title="trading-poc", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DomainException)
async def _domain_exception_handler(
    request: Request, exc: DomainException
) -> JSONResponse:
    """Translate a raised ``DomainException`` into an ``ApiResponse`` envelope.

    The envelope's ``statusCode`` is the exception's ``error_code`` (a
    ``CustomExceptionCodes`` value in the 6xx range), and ``error`` is the
    exception's message. The HTTP status of the response itself stays at
    200 so callers can always read the envelope body without special-casing
    non-2xx codes.
    """
    log.warning(
        "domain_exception",
        path=request.url.path,
        code=int(exc.error_code),
        error=str(exc),
    )
    return JSONResponse(content=ApiResponse.from_exception(exc).model_dump())


@app.exception_handler(Exception)
async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch-all handler — returns a 500-style envelope for anything unexpected.

    Keeps the response shape uniform even for bugs. The original exception
    is logged but its message is NOT leaked in the ``error`` field to avoid
    exposing stack-trace detail to callers.
    """
    log.exception(
        "unhandled_exception", path=request.url.path, error_type=type(exc).__name__
    )
    return JSONResponse(
        status_code=500,
        content=ApiResponse(
            statusCode=500, message=None, result=None, error="Internal server error"
        ).model_dump(),
    )


app.include_router(analyze_router)
app.include_router(trade_router)
app.include_router(trades_router)
app.include_router(signals_router)
app.include_router(audit_router)
app.include_router(admin_router)
app.include_router(config_router)
app.include_router(runner_router)
app.include_router(report_router)
app.include_router(ops_router)
app.include_router(watchlist_router)
app.include_router(optimize_router)
app.include_router(ws_router)


_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(_FRONTEND_DIR):
    app.mount("/ui", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")


@app.get("/")
def read_root() -> dict[str, str]:
    s = get_settings()
    return {"message": "trading-poc is running", "mode": s.mode}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def run_api_server() -> None:
    """Run the FastAPI server with Uvicorn.

    Lets you launch/debug the app by running `python app/main.py` directly
    (or hitting F5 in VS Code). Uvicorn is imported lazily so unit tests and
    other library-level imports of this module don't pull it in.
    """
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level=s.log_level.lower(),
    )


if __name__ == "__main__":
    run_api_server()
