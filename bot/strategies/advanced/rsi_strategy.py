# bot/strategies/advanced/rsi_strategy.py

from __future__ import annotations
from collections import deque
from typing import Optional, Deque

from bot.strategies.base import Strategy
from bot.strategies.signals import StrategySignal
from bot.core.logger import get_logger

from bot.strategies.indicators.rsi import rsi
from bot.strategies.indicators.volatility import volatility_stddev

logger = get_logger(__name__)


class RSIStrategy(Strategy):
    """
    RSI-based mean reversion:

        - ENTER when RSI < lower_threshold (oversold)
        - EXIT  when RSI > upper_threshold (overbought)

    Unified on_bar design that works with fast + full backtest pipelines.
    """

    def __init__(self, params: dict | None = None):
        super().__init__(params or {})

        # RSI configuration
        self.period = int(self.params.get("period", 14))
        self.lower = float(self.params.get("lower", 30.0))
        self.upper = float(self.params.get("upper", 70.0))

        # Optional volatility filter
        self.use_volatility = bool(self.params.get("use_volatility", False))
        self.vol_window = int(self.params.get("vol_window", 20))
        self.vol_mult = float(self.params.get("vol_mult", 1.0))

        # Risk management
        self.stop_loss_pct = float(self.params.get("stop_loss_pct", 0.0))
        self.take_profit_pct = float(self.params.get("take_profit_pct", 0.0))

        # Rolling history
        max_history = int(self.params.get("max_history", self.period * 4))
        self.closes: Deque[float] = deque(maxlen=max_history)

        # Internal indicator state
        self.rsi_val: Optional[float] = None
        self.prev_avg_gain = None
        self.prev_avg_loss = None
        self.volatility: Optional[float] = None

        # Position state
        self.in_position = False
        self.entry_price: Optional[float] = None

    def reset(self):
        self.closes.clear()
        self.rsi_val = None
        self.prev_avg_gain = None
        self.prev_avg_loss = None
        self.volatility = None
        self.in_position = False
        self.entry_price = None

    # --------------------------------------------------------------
    # Indicator computation
    # --------------------------------------------------------------
    def _update_indicators(self):
        if len(self.closes) < self.period:
            self.rsi_val = None
            self.volatility = None
            return

        arr = list(self.closes)

        result = rsi(
            arr,
            self.period,
            prev_avg_gain=self.prev_avg_gain,
            prev_avg_loss=self.prev_avg_loss,
        )

        if result is None:
            self.rsi_val = None
            return

        r, avg_gain, avg_loss = result

        self.rsi_val = float(r)
        self.prev_avg_gain = avg_gain
        self.prev_avg_loss = avg_loss

        if self.use_volatility:
            self.volatility = volatility_stddev(arr, self.vol_window)
        else:
            self.volatility = None

    def _has_data(self) -> bool:
        return self.rsi_val is not None

    # --------------------------------------------------------------
    # MAIN STRATEGY ENTRY POINT
    # --------------------------------------------------------------
    def on_bar(self, candle):
        price = float(candle.close)
        ts = candle.timestamp

        # Update rolling history and indicators
        self.closes.append(price)
        self._update_indicators()

        if not self._has_data():
            return None

        metadata = {
            "price": price,
            "rsi": self.rsi_val,
            "volatility": self.volatility,
            "in_position": self.in_position,
        }

        # ==========================================================
        # STOP LOSS / TAKE PROFIT
        # ==========================================================
        if self.in_position and self.entry_price is not None:
            # Stop-loss
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

            # Take-profit
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

        # ==========================================================
        # ENTRY (RSI oversold)
        # ==========================================================
        if not self.in_position and self.rsi_val < self.lower:
            self.in_position = True
            self.entry_price = price

            return StrategySignal(
                signal_type="ENTER",
                price=price,
                timestamp=ts,
                metadata=metadata | {"reason": "rsi_oversold"},
            )

        # ==========================================================
        # EXIT (RSI overbought)
        # ==========================================================
        if self.in_position and self.rsi_val > self.upper:
            self.in_position = False

            return StrategySignal(
                signal_type="EXIT",
                price=price,
                timestamp=ts,
                metadata=metadata | {"reason": "rsi_overbought"},
            )

        # ==========================================================
        # HOLD
        # ==========================================================
        return StrategySignal(
            signal_type="HOLD",
            price=price,
            timestamp=ts,
            metadata=metadata,
        )
