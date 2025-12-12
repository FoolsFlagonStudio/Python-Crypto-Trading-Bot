# bot/strategies/advanced/breakout.py

from __future__ import annotations
from collections import deque
from typing import Optional, Deque

from bot.strategies.base import Strategy
from bot.strategies.signals import StrategySignal
from bot.strategies.indicators.volatility import atr
from bot.core.logger import get_logger

logger = get_logger(__name__)


class BreakoutStrategy(Strategy):
    """
    Breakout strategy using highest-high & lowest-low lookback levels.

    Entry:
      - Price breaks ABOVE highest-high + buffer

    Exit:
      - Price breaks BELOW lowest-low  - buffer
      - OR hit stop_loss / take_profit if configured

    Buffers:
      - ATR * atr_mult   (recommended)
      - OR % buffer (buffer_pct * level)
    """

    def __init__(self, params: dict | None = None):
        super().__init__(params or {})

        # Core breakout params
        self.lookback = int(self.params.get("lookback", 20))
        if self.lookback <= 0:
            raise ValueError("lookback must be positive")

        self.use_atr = bool(self.params.get("use_atr", True))
        self.atr_period = int(self.params.get("atr_period", 14))
        self.atr_mult = float(self.params.get("atr_mult", 1.0))
        self.buffer_pct = float(self.params.get("buffer_pct", 0.0))

        # Optional risk management on the strategy side
        self.stop_loss_pct = float(self.params.get("stop_loss_pct", 0.0))
        self.take_profit_pct = float(self.params.get("take_profit_pct", 0.0))

        # History buffers
        max_history = int(self.params.get("max_history", self.lookback * 4))
        self.highs: Deque[float] = deque(maxlen=max_history)
        self.lows: Deque[float] = deque(maxlen=max_history)
        self.closes: Deque[float] = deque(maxlen=max_history)

        # Indicator state
        self.atr_val: Optional[float] = None

        # Position state
        self.in_position: bool = False
        self.entry_price: Optional[float] = None

    # ---------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------
    def reset(self):
        self.highs.clear()
        self.lows.clear()
        self.closes.clear()
        self.atr_val = None
        self.in_position = False
        self.entry_price = None

    # ---------------------------------------------------------
    # Indicator & level helpers
    # ---------------------------------------------------------
    def _update_indicators(self, candle):
        self.highs.append(float(candle.high))
        self.lows.append(float(candle.low))
        self.closes.append(float(candle.close))

        # ATR over recent history (if enabled)
        self.atr_val = atr(
            self.highs,
            self.lows,
            self.closes,
            period=self.atr_period,
            prev_atr=self.atr_val,
        )

    def _has_enough_data(self) -> bool:
        return len(self.closes) >= self.lookback

    def _highest_high(self) -> Optional[float]:
        if not self._has_enough_data():
            return None
        arr = list(self.highs)
        return max(arr[-self.lookback:])

    def _lowest_low(self) -> Optional[float]:
        if not self._has_enough_data():
            return None
        arr = list(self.lows)
        return min(arr[-self.lookback:])

    def _compute_buffer(self, level: float) -> float:
        """
        Buffer to avoid constant whipsaws directly at the breakout level.
        Priority:
          1) ATR * atr_mult (if enabled and available)
          2) buffer_pct * level
          3) 0.0
        """
        if level is None:
            return 0.0

        if self.use_atr and self.atr_val:
            return self.atr_val * self.atr_mult

        if self.buffer_pct:
            return level * self.buffer_pct

        return 0.0

    # ---------------------------------------------------------
    # Main per-candle callback
    # ---------------------------------------------------------
    def on_bar(self, candle):
        """
        Called once per candle.
        Returns a StrategySignal or None (None = treated as HOLD by runner).
        """
        price = float(candle.close)
        ts = candle.timestamp

        # Update rolling history & indicators
        self._update_indicators(candle)

        if not self._has_enough_data():
            return None

        highest = self._highest_high()
        lowest = self._lowest_low()

        if highest is None or lowest is None:
            return None

        up_buffer = self._compute_buffer(highest)
        down_buffer = self._compute_buffer(lowest)

        breakout_up_level = highest + up_buffer
        breakdown_level = lowest - down_buffer

        metadata = {
            "price": price,
            "highest_high": highest,
            "lowest_low": lowest,
            "atr": self.atr_val,
            "atr_period": self.atr_period,
            "atr_mult": self.atr_mult,
            "buffer_pct": self.buffer_pct,
            "breakout_up_level": breakout_up_level,
            "breakdown_level": breakdown_level,
            "in_position": self.in_position,
        }

        # =====================================================
        # ENTRY: Breakout UP
        # =====================================================
        if not self.in_position and price > breakout_up_level:
            self.in_position = True
            self.entry_price = price

            logger.info(
                "[BREAKOUT] ENTER: close=%.2f above breakout=%.2f",
                price,
                breakout_up_level,
            )

            return StrategySignal(
                signal_type="ENTER",
                price=price,
                timestamp=ts,
                metadata=metadata | {"reason": "breakout_up"},
            )

        # =====================================================
        # EXIT: Breakdown or SL/TP
        # =====================================================
        if self.in_position and self.entry_price is not None:
            # Optional stop loss / take profit checks
            if self.stop_loss_pct > 0:
                sl_level = self.entry_price * \
                    (1.0 - self.stop_loss_pct / 100.0)
                if price <= sl_level:
                    self.in_position = False
                    logger.info(
                        "[BREAKOUT] EXIT (stop_loss): price=%.2f <= SL=%.2f",
                        price,
                        sl_level,
                    )
                    return StrategySignal(
                        signal_type="EXIT",
                        price=price,
                        timestamp=ts,
                        metadata=metadata | {"reason": "stop_loss"},
                    )

            if self.take_profit_pct > 0:
                tp_level = self.entry_price * \
                    (1.0 + self.take_profit_pct / 100.0)
                if price >= tp_level:
                    self.in_position = False
                    logger.info(
                        "[BREAKOUT] EXIT (take_profit): price=%.2f >= TP=%.2f",
                        price,
                        tp_level,
                    )
                    return StrategySignal(
                        signal_type="EXIT",
                        price=price,
                        timestamp=ts,
                        metadata=metadata | {"reason": "take_profit"},
                    )

            # Normal breakdown exit
            if price < breakdown_level:
                self.in_position = False
                logger.info(
                    "[BREAKOUT] EXIT: close=%.2f below breakdown=%.2f",
                    price,
                    breakdown_level,
                )
                return StrategySignal(
                    signal_type="EXIT",
                    price=price,
                    timestamp=ts,
                    metadata=metadata | {"reason": "breakout_down"},
                )

        # =====================================================
        # HOLD (no trade action)
        # =====================================================
        return StrategySignal(
            signal_type="HOLD",
            price=price,
            timestamp=ts,
            metadata=metadata,
        )
