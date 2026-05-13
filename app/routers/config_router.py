"""View & mutate runtime config. All toggles live in :class:`Settings`."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from pathlib import Path
from typing import Any
import yaml

from app.config import get_settings, reload_settings
from app.exceptions.domain import InvalidRequestException
from app.models.api import ApiResponse, ConfigPatchOut, ConfigReloadOut
from app.routers.deps import reset_cached_singletons
from app.services.angel_session import reset_angel_session

router = APIRouter(prefix="/config", tags=["config"])


_EDITABLE_FIELDS = {
    "mode",
    "broker",
    "paper_trade",
    "enabled_strategies",
    "default_lot_size",
    "openrouter_enabled",
    "openrouter_model",
    "agent_preset",
    "ai_fallback_approve_threshold",
    "openrouter_daily_usd_cap",
    "memory_source",
    "memory_k",
    "rag_enabled",
    "capital_inr",
    "max_risk_per_trade_pct",
    "max_daily_loss_pct",
    "max_open_positions",
    "max_trades_per_day",
    "kill_switch",
    "block_expiry_last_hours",
    "regime_filter_enabled",
    "require_htf_agreement",
    "kelly_sizing_enabled",
    "min_strategy_agreement",
    "min_signal_confidence",
    "signal_memory_ticks",
}


class ConfigPatch(BaseModel):
    """Partial update body for ``PATCH /config`` — only supplied fields change."""

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
    regime_filter_enabled: bool | None = None
    require_htf_agreement: bool | None = None
    kelly_sizing_enabled: bool | None = None
    min_strategy_agreement: int | None = None
    min_signal_confidence: float | None = None
    signal_memory_ticks: int | None = None


def _safe_view() -> dict:
    """Return ``Settings`` as a dict with secret fields masked."""
    s = get_settings()
    data = s.model_dump()
    for k in (
        "openrouter_api_key",
        "kite_api_secret",
        "kite_access_token",
        "angel_api_secret",
        "angel_pin",
        "angel_totp_secret",
    ):
        if data.get(k):
            data[k] = "***set***"
    data["is_live_effective"] = s.is_live()
    return data


@router.get("", response_model=ApiResponse[dict])
def view_config() -> ApiResponse[dict]:
    """Return the live Settings snapshot with secret fields masked."""
    return ApiResponse[dict].ok(_safe_view())


@router.patch("", response_model=ApiResponse[ConfigPatchOut])
def patch_config(patch: ConfigPatch) -> ApiResponse[ConfigPatchOut]:
    """Apply in-memory config changes (does NOT write .env)."""
    s = get_settings()
    changes: dict = {}
    for k, v in patch.model_dump(exclude_none=True).items():
        if k not in _EDITABLE_FIELDS:
            raise InvalidRequestException(f"field '{k}' not editable at runtime")
        setattr(s, k, v)
        changes[k] = v
    reset_cached_singletons()
    return ApiResponse[ConfigPatchOut].ok(
        ConfigPatchOut(applied=changes, config=_safe_view())
    )


@router.post("/reload", response_model=ApiResponse[ConfigReloadOut])
def reload_from_env() -> ApiResponse[ConfigReloadOut]:
    """Re-read .env from disk and rebuild cached broker/agents."""
    reload_settings()
    reset_cached_singletons()
    reset_angel_session()
    return ApiResponse[ConfigReloadOut].ok(
        ConfigReloadOut(reloaded=True, config=_safe_view())
    )


_PARAMS_DIR = Path("config")


@router.get("/params/{symbol}", response_model=ApiResponse[dict])
def get_params(symbol: str) -> ApiResponse[dict]:
    """Return the Optuna-optimized strategy params for a symbol.

    Args:
        symbol: Trading symbol (case-insensitive).

    Returns:
        ApiResponse with ``symbol`` and ``params`` dict (empty if not optimized yet).
    """
    path = _PARAMS_DIR / f"params_{symbol.lower()}.yaml"
    if not path.exists():
        return ApiResponse[dict].ok({"symbol": symbol.upper(), "params": {}})
    data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    return ApiResponse[dict].ok({"symbol": symbol.upper(), "params": data})


@router.post("/params/{symbol}", response_model=ApiResponse[dict])
def save_params(symbol: str, body: dict) -> ApiResponse[dict]:
    """Write strategy params for a symbol to its YAML file.

    Merges the supplied dict into the existing file (so partial updates work).
    Only keys present in the request body are updated; all other strategies
    in the file are preserved.

    Args:
        symbol: Trading symbol (case-insensitive).
        body: Dict mapping strategy name -> param dict (same shape as the YAML file).

    Returns:
        ApiResponse confirming the write with the full updated params.
    """
    _PARAMS_DIR.mkdir(parents=True, exist_ok=True)
    path = _PARAMS_DIR / f"params_{symbol.lower()}.yaml"
    existing: dict[str, Any] = {}
    if path.exists():
        existing = yaml.safe_load(path.read_text()) or {}
    existing.update(body)
    path.write_text(yaml.dump(existing, default_flow_style=False))
    return ApiResponse[dict].ok(
        {"symbol": symbol.upper(), "params": existing, "saved": True}
    )
