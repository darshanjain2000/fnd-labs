from app.strategies.base import Signal, Strategy
from app.strategies.ema_breakout import EMABreakout
from app.strategies.rsi_reversal import RSIReversal
from app.strategies.vwap_pullback import VWAPPullback

ALL_STRATEGIES: list[type[Strategy]] = [RSIReversal, EMABreakout, VWAPPullback]

__all__ = ["Signal", "Strategy", "RSIReversal", "EMABreakout", "VWAPPullback", "ALL_STRATEGIES"]
