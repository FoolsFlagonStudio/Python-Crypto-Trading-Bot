# bot/strategies/advanced/support_resistance_strategy.py

from __future__ import annotations
from collections import deque
from typing import Optional, Deque

from bot.strategies.base import Strategy
from bot.strategies.signals import StrategySignal
from bot.core.logger import get_logger

from bot.strategies.indicators.support_resistance import (
    find_support_resistance,
    bounce_from_support,
    reject_from_resistance,
)

logger = get_logger(__name__)


class SupportResistanceStrategy(Strategy):
    """
    Simple Support/Resistance bounce strategy:

        ENTER:
            - Price is near support
            - Price shows upward reversal

        EXIT:
            - Price is near resistance
            - Price shows downward rejection

    Notes:
        This strategy is inherently noisy on low timeframes.
        Works best on 15m / 1h candles.
    """

    def __init__(self, params: dict | None = None):
        super().__init__(params or {})

        # Pivot detection parameters
        self.left = int(self.params.get("left", 3))
        self.right = int(self.params.get("right", 3))
        self.lookback = int(self.params.get("lookback", 50))
        self.tolerance_pct = float(self.params.get("tolerance_pct", 0.005))

        # Optional risk parameters
        self.stop_loss_pct = float(self.params.get("stop_loss_pct", 0.0))
        self.take_profit_pct = float(self.params.get("take_profit_pct", 0.0))

        max_hist = int(self.params.get("max_history", self.lookback * 2))
        self.highs: Deque[float] = deque(maxlen=max_hist)
        self.lows: Deque[float] = deque(maxlen=max_hist)
        self.closes: Deque[float] = deque(maxlen=max_hist)

        # S/R levels
        self.support: Optional[float] = None
        self.resistance: Optional[float] = None

        # Position state
        self.in_position = False
        self.entry_price: Optional[float] = None

    def reset(self):
        self.highs.clear()
        self.lows.clear()
        self.closes.clear()
        self.support = None
        self.resistance = None
        self.in_position = False
        self.entry_price = None

    # ----------------------------------------------------------
    # Level Detection
    # ----------------------------------------------------------
    def _update_levels(self):
        self.support, self.resistance = find_support_resistance(
            highs=self.highs,
            lows=self.lows,
            left=self.left,
            right=self.right,
            lookback=self.lookback,
        )

    # ----------------------------------------------------------
    # Strategy Entry Point
    # ----------------------------------------------------------
    def on_bar(self, candle):
        price = float(candle.close)
        ts = candle.timestamp

        # Feed rolling windows
        self.highs.append(float(candle.high))
        self.lows.append(float(candle.low))
        self.closes.append(price)

        # Not enough data yet
        if len(self.closes) < self.lookback:
            return None

        # Update levels
        self._update_levels()
        prev_price = self.closes[-2]

        # Metadata
        metadata = {
            "price": price,
            "support": self.support,
            "resistance": self.resistance,
            "in_position": self.in_position,
        }

        # ======================================================
        # RISK: Stop loss / Take profit
        # ======================================================
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

        # ======================================================
        # ENTRY: Bounce from support
        # ======================================================
        if (
            not self.in_position
            and self.support is not None
            and bounce_from_support(
                close=price,
                prev_close=prev_price,
                support=self.support,
                tolerance_pct=self.tolerance_pct,
            )
        ):
            self.in_position = True
            self.entry_price = price
            return StrategySignal(
                signal_type="ENTER",
                price=price,
                timestamp=ts,
                metadata=metadata | {"reason": "bounce_from_support"},
            )

        # ======================================================
        # EXIT: Rejection from resistance
        # ======================================================
        if (
            self.in_position
            and self.resistance is not None
            and reject_from_resistance(
                close=price,
                prev_close=prev_price,
                resistance=self.resistance,
                tolerance_pct=self.tolerance_pct,
            )
        ):
            self.in_position = False
            return StrategySignal(
                signal_type="EXIT",
                price=price,
                timestamp=ts,
                metadata=metadata | {"reason": "reject_from_resistance"},
            )

        # ======================================================
        # HOLD
        # ======================================================
        return StrategySignal(
            signal_type="HOLD",
            price=price,
            timestamp=ts,
            metadata=metadata,
        )
