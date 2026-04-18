from strategies.base import Signal, Strategy
from strategies.ema_breakout import EMABreakout
from strategies.rsi_reversal import RSIReversal
from strategies.vwap_pullback import VWAPPullback

ALL_STRATEGIES: list[type[Strategy]] = [RSIReversal, EMABreakout, VWAPPullback]

__all__ = ["Signal", "Strategy", "RSIReversal", "EMABreakout", "VWAPPullback", "ALL_STRATEGIES"]
