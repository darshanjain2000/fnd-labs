from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.admin import router as admin_router
from api.analyze import router as analyze_router
from api.config_router import router as config_router
from api.trade import router as trade_router
from api.trades import audit_router, router as trades_router, signals_router
from config import get_settings
from core.logging import configure_logging
from db import init_db

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


def run_api_server():
    """Run the FastAPI server with Uvicorn"""
    # We import here to allow running the process without loading API dependencies
    import uvicorn
    uvicorn.run(
        "main:app", 
        host="localhost", 
        port=8000
    )

if __name__ == "__main__":
    run_api_server() 