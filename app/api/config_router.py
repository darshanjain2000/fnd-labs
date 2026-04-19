"""View & mutate runtime config. All toggles live in Settings; this exposes them."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import reset_cached_singletons
from app.config import get_settings, reload_settings
from app.services.angel_session import reset_angel_session

router = APIRouter(prefix="/config", tags=["config"])


_EDITABLE_FIELDS = {
    "mode", "broker", "paper_trade",
    "enabled_strategies", "default_lot_size",
    "openrouter_enabled", "openrouter_model", "agent_preset",
    "ai_fallback_approve_threshold", "openrouter_daily_usd_cap",
    "memory_source", "memory_k",
    "rag_enabled",
    "capital_inr", "max_risk_per_trade_pct", "max_daily_loss_pct",
    "max_open_positions", "max_trades_per_day",
    "kill_switch", "block_expiry_last_hours",
}


class ConfigPatch(BaseModel):
    # Every field is optional — send only what you want to change.
    model_config = {"extra": "forbid"}

    mode: str | None = None
    broker: str | None = None
    paper_trade: bool | None = None
    enabled_strategies: str | None = None
    default_lot_size: int | None = None
    openrouter_enabled: bool | None = None
    openrouter_model: str | None = None
    agent_preset: str | None = None
    ai_fallback_approve_threshold: float | None = None
    openrouter_daily_usd_cap: float | None = None
    memory_source: str | None = None
    memory_k: int | None = None
    rag_enabled: bool | None = None
    capital_inr: float | None = None
    max_risk_per_trade_pct: float | None = None
    max_daily_loss_pct: float | None = None
    max_open_positions: int | None = None
    max_trades_per_day: int | None = None
    kill_switch: bool | None = None
    block_expiry_last_hours: int | None = None


def _safe_view() -> dict:
    s = get_settings()
    data = s.model_dump()
    # Mask secrets.
    for k in ("openrouter_api_key", "kite_api_secret", "kite_access_token", "angel_api_secret", "angel_pin", "angel_totp_secret"):
        if data.get(k):
            data[k] = "***set***"
    data["is_live_effective"] = s.is_live()
    return data


@router.get("")
def view_config() -> dict:
    return _safe_view()


@router.patch("")
def patch_config(patch: ConfigPatch) -> dict:
    """Apply in-memory config changes (does NOT write .env). Cleared singletons reload next call."""
    s = get_settings()
    changes: dict = {}
    for k, v in patch.model_dump(exclude_none=True).items():
        if k not in _EDITABLE_FIELDS:
            raise HTTPException(400, f"field '{k}' not editable at runtime")
        setattr(s, k, v)
        changes[k] = v
    reset_cached_singletons()
    return {"applied": changes, "config": _safe_view()}


@router.post("/reload")
def reload_from_env() -> dict:
    """Re-read .env from disk and rebuild cached broker/agents."""
    reload_settings()
    reset_cached_singletons()
    reset_angel_session()
    return {"reloaded": True, "config": _safe_view()}
