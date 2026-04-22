from __future__ import annotations

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

    # ---- Phase 3: Regime-aware routing --------------------------------
    regime_filter_enabled: bool = True
    """If True, strategies only run in their preferred market regimes."""

    # ---- Phase 3: Multi-timeframe confirmation -----------------------
    require_htf_agreement: bool = False
    """If True, a signal is rejected unless the HTF EMA trend agrees with side."""
    htf_interval: str = "15min"
    """Pandas resample rule for the higher-timeframe candles (e.g. '15min', '1h')."""

    # ---- Phase 3: Kelly position sizing ------------------------------
    kelly_sizing_enabled: bool = False
    """If True, apply a half-Kelly multiplier to risk_pct using recent trade history."""
    kelly_lookback_trades: int = 20
    """Number of recent closed trades used to estimate Kelly fraction."""

    # ---- Phase 3: Ensemble conviction --------------------------------
    min_strategy_agreement: int = 2
    """Minimum strategies that must fire on the *same side* for a symbol
    before the orchestrator will process any signal. Set to 2+ for ensemble
    voting. Set to 1 to let any single strategy trade."""
    min_signal_confidence: float = 0.5
    """Minimum strategy confidence required for a signal to be considered.
    Signals below this threshold are silently dropped."""
    signal_memory_ticks: int = 3
    """Number of recent ticks to remember signals from per symbol.
    Allows conviction to build across candles (e.g. RSI fires tick 1,
    EMA fires tick 3 -> both count). Set to 1 to disable memory."""

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

    # ---- Intraday runner (live-data paper trading loop) --------------
    auto_run_enabled: bool = False
    """If true, the scheduler starts automatically at app boot and runs during market hours."""
    watchlist: str = "NIFTY:NSE,BANKNIFTY:NSE"
    """Comma-separated SYMBOL:EXCHANGE pairs the runner polls each tick."""
    run_interval_sec: int = 60
    """How often (seconds) to fetch a fresh candle batch per symbol during market hours."""
    run_candle_interval: str = "1m"
    """Candle interval fed to strategies (1m, 3m, 5m, 15m, 30m, 1h)."""
    fetch_stagger_ms: int = 350
    """Milliseconds to wait between starting each parallel candle fetch.

    Angel One enforces a per-second request cap. Staggering avoids sending all
    watchlist requests simultaneously and triggering 'Access denied / rate exceeded'.
    With 8 symbols and 350ms: last request starts at 2.45s, well within the 60s tick.
    Set to 0 to disable staggering (not recommended for watchlists > 3 symbols).
    Read from FETCH_STAGGER_MS in .env.
    """
    fetch_max_concurrent: int = 3
    """Maximum number of candle fetch requests to Angel One that may run at the same time.

    Acts as a hard concurrency cap (asyncio.Semaphore) — even if stagger fires all
    coroutines, only this many will be in-flight to Angel simultaneously.
    Keeps the request rate well within Angel One's API rate limits.
    Read from FETCH_MAX_CONCURRENT in .env.
    """
    market_open: str = "09:15"
    """Market open time (IST, 24h HH:MM)."""
    market_close: str = "15:30"
    """Market close time (IST, 24h HH:MM)."""
    square_off_time: str = "15:20"
    """Force-close all open paper trades at this IST time (before market close)."""

    # ---- Storage / logging ------------------------------------------
    database_url: str = "sqlite:///./trading.db"
    log_level: str = "INFO"
    log_format: Literal["pretty", "json"] = "pretty"
    """'pretty' = human-readable colored console, 'json' = structured logs for prod."""
    log_heartbeat_interval_sec: int = 300
    """Emit a live-status heartbeat log every N seconds while the market is open.

    Shows tick count, open positions, realized P&L, and uptime.
    Set to 0 to disable. Read from LOG_HEARTBEAT_INTERVAL_SEC in .env.
    """

    # ---- Helpers -----------------------------------------------------
    def strategy_list(self) -> list[str]:
        return [s.strip() for s in self.enabled_strategies.split(",") if s.strip()]

    def watchlist_pairs(self) -> list[tuple[str, str]]:
        """Parse WATCHLIST='SYM1:EXCH1,SYM2:EXCH2' into [(sym, exch), ...]."""
        out: list[tuple[str, str]] = []
        for entry in self.watchlist.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" in entry:
                sym, exch = entry.split(":", 1)
                out.append((sym.strip(), exch.strip()))
            else:
                out.append((entry, "NSE"))
        return out

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

