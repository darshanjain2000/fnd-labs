from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BrokerName = Literal["paper", "kite", "angel"]
AgentPreset = Literal["conservative", "balanced", "aggressive"]


class Settings(BaseSettings):
    """Single source of truth for every toggle. Loaded from .env on startup.

    Change a value in .env and restart uvicorn — no code edits needed.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # ---- Core mode ---------------------------------------------------
    mode: Literal["paper", "live"] = "paper"
    broker: BrokerName = "paper"
    paper_trade: bool = True
    """Force paper simulation even if broker=kite|angel. Safety belt for dry runs."""

    # ---- Strategies --------------------------------------------------
    enabled_strategies: str = "rsi_reversal,ema_breakout,vwap_pullback"
    """Comma-separated subset of strategies to run. Empty = none."""

    default_lot_size: int = 1

    # ---- AI layer ----------------------------------------------------
    openrouter_enabled: bool = True
    """Master switch for LLM validation. Off = strategies alone decide."""
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-3.5-sonnet"
    openrouter_daily_usd_cap: float = 0.30
    agent_preset: AgentPreset = "balanced"
    """Controls validation-agent system prompt tone & confidence threshold."""
    ai_fallback_approve_threshold: float = 0.6
    """When LLM unavailable, approve if strategy confidence >= this value."""

    # ---- Memory / context for the LLM -------------------------------
    memory_source: Literal["db", "rag", "off"] = "db"
    """How to fetch similar past-trade context for the validation agent.

    - "db"  : SQL query over the trades table (fast, deterministic, default)
    - "rag" : Chroma vector search (requires rag_enabled=true, heavier)
    - "off" : skip similar-trade context entirely
    """
    memory_k: int = 5

    # ---- RAG ---------------------------------------------------------
    rag_enabled: bool = False
    chroma_path: str = "./.chroma"

    # ---- Broker: Kite ------------------------------------------------
    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""

    # ---- Broker: Angel One ------------------------------------------
    angel_api_key: str = ""
    angel_api_secret: str = ""
    angel_client_code: str = ""
    angel_pin: str = ""
    angel_totp_secret: str = ""

    # ---- Risk --------------------------------------------------------
    capital_inr: float = 25000.0
    max_risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 2.0
    max_open_positions: int = 3
    max_trades_per_day: int = 5

    # ---- Safety ------------------------------------------------------
    kill_switch: bool = False
    block_expiry_last_hours: int = 2

    # ---- Storage / logging ------------------------------------------
    database_url: str = "sqlite:///./trading.db"
    log_level: str = "INFO"

    # ---- Helpers -----------------------------------------------------
    def strategy_list(self) -> list[str]:
        return [s.strip() for s in self.enabled_strategies.split(",") if s.strip()]

    def is_live(self) -> bool:
        """Actually place real orders? Requires mode=live AND paper_trade=false."""
        return self.mode == "live" and not self.paper_trade


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Force a fresh read of .env (useful in tests / admin endpoints)."""
    get_settings.cache_clear()
    return get_settings()

