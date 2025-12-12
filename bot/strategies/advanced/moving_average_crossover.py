# bot/strategies/advanced/moving_average_crossover.py

from __future__ import annotations
from collections import deque
from typing import Optional, Deque

from bot.strategies.base import Strategy
from bot.strategies.signals import StrategySignal
from bot.core.logger import get_logger

logger = get_logger(__name__)


def ema(prev: Optional[float], price: float, period: int) -> float:
    """Simple streaming EMA update."""
    if prev is None:
        return price
    k = 2.0 / (period + 1)
    return price * k + prev * (1 - k)


class MovingAverageCrossoverStrategy(Strategy):
    """
    Classic EMA crossover:

        - Bullish crossover: fast EMA crosses ABOVE slow EMA
        - Bearish crossover: fast EMA crosses BELOW slow EMA

    Uses a unified `on_bar` loop compatible with FastBacktestEngine.
    """

    def __init__(self, params: dict | None = None):
        super().__init__(params or {})

        # EMA windows
        self.fast_window = int(self.params.get("fast_window", 9))
        self.slow_window = int(self.params.get("slow_window", 21))

        if self.fast_window >= self.slow_window:
            logger.warning("Fast window >= slow window — unusual config.")

        # Optional breakout strength filter
        self.buffer_pct = float(self.params.get("buffer_pct", 0.0))

        # Optional risk controls
        self.stop_loss_pct = float(self.params.get("stop_loss_pct", 0.0))
        self.take_profit_pct = float(self.params.get("take_profit_pct", 0.0))

        # Rolling close buffer
        max_history = int(
            self.params.get("max_history", max(
                self.fast_window, self.slow_window) * 4)
        )
        self.closes: Deque[float] = deque(maxlen=max_history)

        # EMA state
        self.fast_ema: Optional[float] = None
        self.slow_ema: Optional[float] = None
        self.prev_fast_ema: Optional[float] = None
        self.prev_slow_ema: Optional[float] = None

        # Position state
        self.in_position = False
        self.entry_price: Optional[float] = None

    def reset(self):
        self.closes.clear()
        self.fast_ema = None
        self.slow_ema = None
        self.prev_fast_ema = None
        self.prev_slow_ema = None
        self.in_position = False
        self.entry_price = None

    # ---------------------------------------------------------
    # EMA update helpers
    # ---------------------------------------------------------
    def _update_indicators(self, price: float):
        self.closes.append(price)

        # Save previous EMA values for crossover detection
        self.prev_fast_ema = self.fast_ema
        self.prev_slow_ema = self.slow_ema

        # Streaming EMA updates
        self.fast_ema = ema(self.fast_ema, price, self.fast_window)
        self.slow_ema = ema(self.slow_ema, price, self.slow_window)

    def _has_enough_data(self) -> bool:
        return (
            self.fast_ema is not None
            and self.slow_ema is not None
            and self.prev_fast_ema is not None
            and self.prev_slow_ema is not None
        )

    # ---------------------------------------------------------
    # Crossover logic
    # ---------------------------------------------------------
    def _bullish_crossover(self) -> bool:
        if not self._has_enough_data():
            return False

        was_below = self.prev_fast_ema <= self.prev_slow_ema
        is_above = self.fast_ema > self.slow_ema * (1 + self.buffer_pct)

        return was_below and is_above

    def _bearish_crossover(self) -> bool:
        if not self._has_enough_data():
            return False

        was_above = self.prev_fast_ema >= self.prev_slow_ema
        is_below = self.fast_ema < self.slow_ema * (1 - self.buffer_pct)

        return was_above and is_below

    # ---------------------------------------------------------
    # MAIN on_bar LOOP
    # ---------------------------------------------------------
    def on_bar(self, candle):
        price = float(candle.close)
        ts = candle.timestamp

        # Update EMAs
        self._update_indicators(price)

        if not self._has_enough_data():
            return None

        metadata = {
            "price": price,
            "fast_ema": self.fast_ema,
            "slow_ema": self.slow_ema,
            "prev_fast_ema": self.prev_fast_ema,
            "prev_slow_ema": self.prev_slow_ema,
            "in_position": self.in_position,
        }

        # =====================================================
        # OPTIONAL: Stop-loss / take-profit
        # =====================================================
        if self.in_position and self.entry_price is not None:
            if self.stop_loss_pct > 0:
                sl = self.entry_price * (1 - self.stop_loss_pct / 100)
                if price <= sl:
                    self.in_position = False
                    return StrategySignal(
                        signal_type="EXIT",
                        price=price,
                        timestamp=ts,
                        metadata=metadata | {"reason": "stop_loss"},
                    )

            if self.take_profit_pct > 0:
                tp = self.entry_price * (1 + self.take_profit_pct / 100)
                if price >= tp:
                    self.in_position = False
                    return StrategySignal(
                        signal_type="EXIT",
                        price=price,
                        timestamp=ts,
                        metadata=metadata | {"reason": "take_profit"},
                    )

        # =====================================================
        # ENTRY — Bullish crossover
        # =====================================================
        if not self.in_position and self._bullish_crossover():
            self.in_position = True
            self.entry_price = price

            logger.info("[MA_XOVER] ENTER: Fast EMA crossed above slow EMA")

            return StrategySignal(
                signal_type="ENTER",
                price=price,
                timestamp=ts,
                metadata=metadata | {"reason": "bullish_crossover"},
            )

        # =====================================================
        # EXIT — Bearish crossover
        # =====================================================
        if self.in_position and self._bearish_crossover():
            self.in_position = False

            logger.info("[MA_XOVER] EXIT: Fast EMA crossed below slow EMA")

            return StrategySignal(
                signal_type="EXIT",
                price=price,
                timestamp=ts,
                metadata=metadata | {"reason": "bearish_crossover"},
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
