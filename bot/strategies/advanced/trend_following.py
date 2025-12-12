# bot/strategies/advanced/trend_following.py

from __future__ import annotations
from typing import Optional

from bot.strategies.base import Strategy
from bot.strategies.signals import StrategySignal
from bot.core.logger import get_logger

logger = get_logger(__name__)


def ema(prev: float, price: float, period: int) -> float:
    k = 2.0 / (period + 1)
    return price * k + prev * (1 - k)


class TrendFollowingStrategy(Strategy):
    """
    Simple trend-following:

        - Compute EMA
        - ENTER when price > EMA for confirm_period bars
        - EXIT  when price < EMA for confirm_period bars
    """

    def __init__(self, params: dict):
        super().__init__(params)

        self.ema_period = int(self.params.get("ema_period", 50))
        self.confirm_period = int(self.params.get("confirm_period", 3))

        # Internal state
        self.ema_value: Optional[float] = None
        self.above_count = 0
        self.below_count = 0

        self.in_position = False
        self.entry_price: Optional[float] = None

    def reset(self):
        self.ema_value = None
        self.above_count = 0
        self.below_count = 0
        self.in_position = False
        self.entry_price = None

    # -----------------------------------------------------
    # Main per-candle entry point
    # -----------------------------------------------------
    def on_bar(self, candle):
        price = float(candle.close)
        ts = candle.timestamp

        # ------------------------------
        # EMA update
        # ------------------------------
        if self.ema_value is None:
            self.ema_value = price
        else:
            self.ema_value = ema(self.ema_value, price, self.ema_period)

        # ------------------------------
        # Counter logic
        # ------------------------------
        if price > self.ema_value:
            self.above_count += 1
            self.below_count = 0
        elif price < self.ema_value:
            self.below_count += 1
            self.above_count = 0

        # ------------------------------
        # Metadata for debugging
        # ------------------------------
        metadata = {
            "price": price,
            "ema": self.ema_value,
            "above_count": self.above_count,
            "below_count": self.below_count,
            "in_position": self.in_position,
        }

        # =====================================================
        # ENTRY
        # =====================================================
        if not self.in_position and self.above_count >= self.confirm_period:
            self.in_position = True
            self.entry_price = price
            return StrategySignal(
                signal_type="ENTER",
                price=price,
                timestamp=ts,
                metadata=metadata | {"reason": "trend_up"},
            )

        # =====================================================
        # EXIT
        # =====================================================
        if self.in_position and self.below_count >= self.confirm_period:
            self.in_position = False
            return StrategySignal(
                signal_type="EXIT",
                price=price,
                timestamp=ts,
                metadata=metadata | {"reason": "trend_down"},
            )

        # =====================================================
        # HOLD
        # =====================================================
        return StrategySignal(
            signal_type="HOLD",
            price=price,
            timestamp=ts,
            metadata=metadata,
        )
