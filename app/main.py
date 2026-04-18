from contextlib import asynccontextmanager

# When launched as a script (`python app/main.py` from the VS Code debugger),
# the project root isn't on sys.path, so `from app.*` imports fail. Fix it up.
if __name__ == "__main__" or __package__ in (None, ""):
    import sys
    from pathlib import Path
    _ROOT = Path(__file__).resolve().parent.parent
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.analyze import router as analyze_router
from app.api.config_router import router as config_router
from app.api.trade import router as trade_router
from app.api.trades import audit_router, router as trades_router, signals_router
from app.config import get_settings
from app.core.logging import configure_logging
from app.db import init_db

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="trading-poc", version="0.1.0", lifespan=lifespan)

app.include_router(analyze_router)
app.include_router(trade_router)
app.include_router(trades_router)
app.include_router(signals_router)
app.include_router(audit_router)
app.include_router(admin_router)
app.include_router(config_router)


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
