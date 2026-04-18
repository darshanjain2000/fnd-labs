from contextlib import asynccontextmanager

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
