# bot/strategies/advanced/mean_reversion.py

from __future__ import annotations
from collections import deque
from typing import Optional, Deque

from bot.strategies.base import Strategy
from bot.strategies.signals import StrategySignal


class MeanReversionStrategy(Strategy):
    """
    Classic mean reversion using z-score:

        z = (price - mean) / std

    Entry:
        z <= z_entry  (e.g. -2.0)

    Exit:
        z >= z_exit   (e.g. -0.5)

    Includes stop loss + take profit logic.
    """

    def __init__(self, params: dict):
        super().__init__(params)

        # Core parameters
        self.lookback = int(self.params.get("lookback", 20))
        self.z_entry = float(self.params.get("z_entry", -2.0))
        self.z_exit = float(self.params.get("z_exit", -0.5))

        # Trade protection parameters (percentages)
        self.stop_loss_pct = float(self.params.get("stop_loss_pct", 2.0))
        self.take_profit_pct = float(self.params.get("take_profit_pct", 4.0))

        # Rolling window
        self.prices: Deque[float] = deque(maxlen=self.lookback)

        # Position state
        self.in_position: bool = False
        self.entry_price: Optional[float] = None

    def reset(self):
        self.prices.clear()
        self.in_position = False
        self.entry_price = None

    # ---------------------------------------------------------
    # Main strategy callback — called on each candle
    # ---------------------------------------------------------
    def on_bar(self, candle):
        price = float(candle.close)
        ts = candle.timestamp

        # Update buffer
        self.prices.append(price)

        # Not enough data for mean/std → no signal
        if len(self.prices) < self.lookback:
            return None

        mean = sum(self.prices) / len(self.prices)
        variance = sum((p - mean) ** 2 for p in self.prices) / len(self.prices)
        std = variance ** 0.5 if variance > 0 else 1e-8

        z = (price - mean) / std

        # Common metadata for debugging & DB logging
        metadata = {
            "price": price,
            "mean": mean,
            "std": std,
            "z": z,
            "in_position": self.in_position,
        }

        # -----------------------------------------------------
        # ENTRY LOGIC
        # -----------------------------------------------------
        if not self.in_position and z <= self.z_entry:
            self.in_position = True
            self.entry_price = price

            return StrategySignal(
                signal_type="ENTER",
                price=price,
                timestamp=ts,
                metadata=metadata,
            )

        # -----------------------------------------------------
        # EXIT LOGIC
        # -----------------------------------------------------
        if self.in_position:

            # Stop-loss
            if self.entry_price and price <= self.entry_price * (1 - self.stop_loss_pct / 100):
                self.in_position = False
                return StrategySignal(
                    signal_type="EXIT",
                    price=price,
                    timestamp=ts,
                    metadata=metadata | {"reason": "stop_loss"},
                )

            # Take-profit
            if self.entry_price and price >= self.entry_price * (1 + self.take_profit_pct / 100):
                self.in_position = False
                return StrategySignal(
                    signal_type="EXIT",
                    price=price,
                    timestamp=ts,
                    metadata=metadata | {"reason": "take_profit"},
                )

            # Normal exit based on z-score
            if z >= self.z_exit:
                self.in_position = False
                return StrategySignal(
                    signal_type="EXIT",
                    price=price,
                    timestamp=ts,
                    metadata=metadata,
                )

        # -----------------------------------------------------
        # HOLD — no trade action
        # -----------------------------------------------------
        return StrategySignal(
            signal_type="HOLD",
            price=price,      # float only
            timestamp=ts,
            metadata=metadata,
        )
