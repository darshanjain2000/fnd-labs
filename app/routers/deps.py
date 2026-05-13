"""Dependency providers for FastAPI routes.

Each ``get_*`` function is an ``lru_cache``'d builder. Call
:func:`reset_cached_singletons` to invalidate every cache after a config
reload so the next request reads fresh ``Settings``.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.controllers.execution_controller import ExecutionController
from app.controllers.signal_controller import SignalController
from app.controllers.trade_controller import TradeController
from app.controllers.validation_controller import ValidationController
from app.core.logging import get_logger
from app.engine.orchestrator import Orchestrator
from app.engine.risk_engine import RiskEngine
from app.rag.store import RAGStore
from app.services.broker.base import Broker
from app.services.broker.paper_broker import PaperBroker
from app.services.signal_service import SignalService
from app.services.validation_service import ValidationService
from app.strategies import ALL_STRATEGIES

log = get_logger(__name__)


_MOCK_QUOTES: dict[str, float] = {}


def set_mock_quote(symbol: str, price: float) -> None:
    """Set a mock quote for ``symbol`` used by :class:`PaperBroker`."""
    _MOCK_QUOTES[symbol] = price


def _mock_quote_fn(symbol: str) -> float:
    return _MOCK_QUOTES.get(symbol, 100.0)


def _build_broker(s: Settings) -> Broker:
    """Return a ``Broker`` matching the active configuration."""
    if s.paper_trade or s.broker == "paper":
        log.info("broker_init", broker="paper", forced_by_flag=s.paper_trade)
        return PaperBroker(quote_fn=_mock_quote_fn)
    if s.broker == "kite":
        from app.services.broker.kite_client import KiteBroker

        log.info("broker_init", broker="kite")
        return KiteBroker()
    if s.broker == "angel":
        from app.services.broker.angel_client import AngelBroker

        log.info("broker_init", broker="angel")
        return AngelBroker()
    log.warning("broker_unknown_fallback_paper", broker=s.broker)
    return PaperBroker(quote_fn=_mock_quote_fn)


def _build_signal_service(s: Settings) -> SignalService:
    """Build a :class:`SignalService` with only the strategies named in settings."""
    selected = set(s.strategy_list())
    strategies = [cls() for cls in ALL_STRATEGIES if cls.name in selected]
    if not strategies:
        log.warning("no_strategies_enabled")
    return SignalService(strategies=strategies, settings=s)


@lru_cache
def get_broker() -> Broker:
    """Return the shared ``Broker`` singleton."""
    return _build_broker(get_settings())


@lru_cache
def get_risk_engine() -> RiskEngine:
    """Return the shared ``RiskEngine`` singleton."""
    return RiskEngine()


@lru_cache
def get_signal_service() -> SignalService:
    """Return the shared :class:`SignalService` configured from current settings."""
    return _build_signal_service(get_settings())


@lru_cache
def get_validation_service() -> ValidationService:
    """Return the shared :class:`ValidationService` singleton."""
    return ValidationService()


@lru_cache
def get_rag() -> RAGStore:
    """Return the shared :class:`RAGStore` singleton."""
    return RAGStore()


@lru_cache
def get_orchestrator() -> Orchestrator:
    """Return the shared :class:`Orchestrator` wired up from the other singletons."""
    s = get_settings()
    return Orchestrator(
        broker=get_broker(),
        risk_engine=get_risk_engine(),
        signal_agent=get_signal_service(),
        validation_agent=get_validation_service(),
        rag=get_rag(),
        lot_size=s.default_lot_size,
    )


@lru_cache
def get_signal_controller() -> SignalController:
    """Return a :class:`SignalController` backed by the cached signal service."""
    return SignalController(service=get_signal_service())


@lru_cache
def get_validation_controller() -> ValidationController:
    """Return a :class:`ValidationController` backed by the cached validation service."""
    return ValidationController(service=get_validation_service())


@lru_cache
def get_execution_controller() -> ExecutionController:
    """Return an :class:`ExecutionController` using the active broker."""
    return ExecutionController(broker=get_broker())


@lru_cache
def get_trade_controller() -> TradeController:
    """Return a :class:`TradeController` (no singleton dependencies)."""
    return TradeController()


def reset_cached_singletons() -> None:
    """Clear all LRU caches so next call re-reads Settings. Used by /config/reload."""
    for fn in (
        get_broker,
        get_signal_service,
        get_validation_service,
        get_orchestrator,
        get_rag,
        get_signal_controller,
        get_validation_controller,
        get_execution_controller,
        get_trade_controller,
    ):
        fn.cache_clear()
