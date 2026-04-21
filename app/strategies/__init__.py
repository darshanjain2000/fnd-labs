from app.strategies.base import Signal, Strategy
from app.strategies.bollinger_squeeze import BollingerSqueeze
from app.strategies.ema_breakout import EMABreakout
from app.strategies.macd_divergence import MACDDivergence
from app.strategies.orb_breakout import ORBBreakout
from app.strategies.rsi_reversal import RSIReversal
from app.strategies.supertrend import SupertrendStrategy
from app.strategies.vwap_pullback import VWAPPullback

ALL_STRATEGIES: list[type[Strategy]] = [
    RSIReversal,
    EMABreakout,
    VWAPPullback,
    SupertrendStrategy,
    MACDDivergence,
    BollingerSqueeze,
    ORBBreakout,
]

__all__ = [
    "Signal",
    "Strategy",
    "RSIReversal",
    "EMABreakout",
    "VWAPPullback",
    "SupertrendStrategy",
    "MACDDivergence",
    "BollingerSqueeze",
    "ORBBreakout",
    "ALL_STRATEGIES",
]
