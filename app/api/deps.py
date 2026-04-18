"""Dependency providers for FastAPI routes. Broker/agent selection driven by Settings."""
from __future__ import annotations

from functools import lru_cache

from agents.signal_agent import SignalAgent
from agents.validation_agent import ValidationAgent
from config import Settings, get_settings
from core.logging import get_logger
from engine.orchestrator import Orchestrator
from engine.risk_engine import RiskEngine
from rag.store import RAGStore
from services.broker.base import Broker
from services.broker.paper_broker import PaperBroker
from strategies import ALL_STRATEGIES

log = get_logger(__name__)

# Mock quote store used by PaperBroker absent a live feed.
_MOCK_QUOTES: dict[str, float] = {}


def set_mock_quote(symbol: str, price: float) -> None:
    _MOCK_QUOTES[symbol] = price


def _mock_quote_fn(symbol: str) -> float:
    return _MOCK_QUOTES.get(symbol, 100.0)


# ---- Builders (not cached; respect current Settings) -------------------
def _build_broker(s: Settings) -> Broker:
    if s.paper_trade or s.broker == "paper":
        log.info("broker_init", broker="paper", forced_by_flag=s.paper_trade)
        return PaperBroker(quote_fn=_mock_quote_fn)
    if s.broker == "kite":
        from services.broker.kite_client import KiteBroker
        log.info("broker_init", broker="kite")
        return KiteBroker()
    if s.broker == "angel":
        from services.broker.angel_client import AngelBroker
        log.info("broker_init", broker="angel")
        return AngelBroker()
    log.warning("broker_unknown_fallback_paper", broker=s.broker)
    return PaperBroker(quote_fn=_mock_quote_fn)


def _build_signal_agent(s: Settings) -> SignalAgent:
    selected = set(s.strategy_list())
    strategies = [cls() for cls in ALL_STRATEGIES if cls().name in selected]
    if not strategies:
        log.warning("no_strategies_enabled")
    return SignalAgent(strategies=strategies)


# ---- Cached singletons --------------------------------------------------
@lru_cache
def get_broker() -> Broker:
    return _build_broker(get_settings())


@lru_cache
def get_risk_engine() -> RiskEngine:
    return RiskEngine()


@lru_cache
def get_signal_agent() -> SignalAgent:
    return _build_signal_agent(get_settings())


@lru_cache
def get_validation_agent() -> ValidationAgent:
    return ValidationAgent()


@lru_cache
def get_rag() -> RAGStore:
    return RAGStore()


@lru_cache
def get_orchestrator() -> Orchestrator:
    s = get_settings()
    return Orchestrator(
        broker=get_broker(),
        risk_engine=get_risk_engine(),
        signal_agent=get_signal_agent(),
        validation_agent=get_validation_agent(),
        rag=get_rag(),
        lot_size=s.default_lot_size,
    )


def reset_cached_singletons() -> None:
    """Clear LRU caches so next call re-reads Settings. Used by /config/reload."""
    for fn in (get_broker, get_signal_agent, get_validation_agent, get_orchestrator, get_rag):
        fn.cache_clear()
