# bot/strategies/advanced/trend_following.py

from __future__ import annotations

from collections import deque
from typing import Optional

from bot.strategies.base import Strategy
from bot.strategies.signals import StrategySignal, SignalType
from bot.strategies.indicators.moving_averages import ema
from bot.strategies.indicators.volatility import atr
from bot.strategies.portfolio_metrics import (
    compute_unrealized_pnl,
    compute_last_trade_info,
    compute_drawdown_status,
)
from bot.core.logger import get_logger

logger = get_logger(__name__)


class TrendFollowingStrategy(Strategy):
    """
    Trend Following Strategy using EMA + confirmation window.

    Entry:
      - Price > EMA for confirm_period consecutive candles

    Exit:
      - Price < EMA for confirm_period consecutive candles

    Metadata:
      - Unrealized P/L
      - ATR & EMA values
      - Last entry price / time since last trade
      - Drawdown info
    """

    def __init__(self, params: dict | None = None):
        super().__init__(params)

        self.ema_period = int(self.params.get("ema_period", 50))
        self.confirm_period = int(self.params.get("confirm_period", 3))

        # buffers
        self.use_atr = bool(self.params.get("use_atr", False))
        self.atr_period = int(self.params.get("atr_period", 14))
        self.atr_mult = float(self.params.get("atr_mult", 1.0))
        self.buffer_pct = float(self.params.get("buffer_pct", 0.0))

        max_history = int(self.params.get("max_history", self.ema_period * 4))

        self.closes = deque(maxlen=max_history)
        self.highs = deque(maxlen=max_history)
        self.lows = deque(maxlen=max_history)

        # states
        self.ema_val: Optional[float] = None
        self.prev_ema: Optional[float] = None
        self.atr_val: Optional[float] = None

        # confirmation counters
        self.above_count = 0
        self.below_count = 0

    # ----------------------------------------------------------------------
    # Indicator Update
    # ----------------------------------------------------------------------

    def _update_indicators(self, candle):
        price = float(candle.close)

        self.closes.append(price)
        self.highs.append(float(candle.high))
        self.lows.append(float(candle.low))

        # EMA update
        new_ema = ema(self.closes, self.ema_period, prev_ema=self.ema_val)
        self.prev_ema = self.ema_val
        self.ema_val = new_ema

        # ATR update
        self.atr_val = atr(
            self.highs,
            self.lows,
            self.closes,
            period=self.atr_period,
            prev_atr=self.atr_val,
        )

    def _has_enough_data(self):
        return self.ema_val is not None and self.prev_ema is not None

    # ----------------------------------------------------------------------
    # Trend Conditions
    # ----------------------------------------------------------------------

    def _price_above_ema(self) -> bool:
        price = self.closes[-1]
        ema_val = self.ema_val

        buffer = 0.0
        if self.use_atr and self.atr_val:
            buffer = self.atr_val * self.atr_mult
        elif self.buffer_pct:
            buffer = ema_val * self.buffer_pct

        return price > (ema_val + buffer)

    def _price_below_ema(self) -> bool:
        price = self.closes[-1]
        ema_val = self.ema_val

        buffer = 0.0
        if self.use_atr and self.atr_val:
            buffer = self.atr_val * self.atr_mult
        elif self.buffer_pct:
            buffer = ema_val * self.buffer_pct

        return price < (ema_val - buffer)

    # ----------------------------------------------------------------------
    # Entry & Exit Logic
    # ----------------------------------------------------------------------

    def should_enter(self, candle, portfolio_state):
        self._update_indicators(candle)

        if not self._has_enough_data():
            return False

        if self._price_above_ema():
            self.above_count += 1
        else:
            self.above_count = 0

        if self.above_count >= self.confirm_period:
            logger.info(
                "[TREND] ENTER: price > EMA for %d candles (EMA=%.2f close=%.2f)",
                self.confirm_period,
                self.ema_val,
                self.closes[-1],
            )
            self.below_count = 0
            return True

        return False

    def should_exit(self, candle, portfolio_state):
        if len(self.closes) == 0:
            self._update_indicators(candle)
            return False

        self._update_indicators(candle)

        if not self._has_enough_data():
            return False

        if self._price_below_ema():
            self.below_count += 1
        else:
            self.below_count = 0

        if self.below_count >= self.confirm_period:
            logger.info(
                "[TREND] EXIT: price < EMA for %d candles (EMA=%.2f close=%.2f)",
                self.confirm_period,
                self.ema_val,
                self.closes[-1],
            )
            self.above_count = 0
            return True

        return False

    # ----------------------------------------------------------------------
    # Enriched Metadata
    # ----------------------------------------------------------------------

    def generate_signal(self, candle, portfolio_state):
        sig = super().generate_signal(candle, portfolio_state)

        if sig.metadata is None:
            sig.metadata = {}

        price = float(candle.close)

        # ---- Portfolio Metrics ----
        unrealized = compute_unrealized_pnl(portfolio_state, price)
        last_entry_price, opened_at, seconds_since = compute_last_trade_info(
            portfolio_state
        )
        dd_state = compute_drawdown_status(
            portfolio_state,
            unrealized_pnl=unrealized,
        )

        # ---- Indicator Metadata ----
        sig.metadata.update(
            {
                "strategy": "trend_following",
                "ema_period": self.ema_period,
                "confirm_period": self.confirm_period,
                "ema": self.ema_val,
                "prev_ema": self.prev_ema,
                "above_count": self.above_count,
                "below_count": self.below_count,
                "atr": self.atr_val,
                "atr_period": self.atr_period,
                "atr_mult": self.atr_mult,
                "buffer_pct": self.buffer_pct,
                "last_close": price,
                # Portfolio & Risk
                "unrealized_pnl": unrealized,
                "last_entry_price": last_entry_price,
                "last_trade_opened_at": opened_at.isoformat() if opened_at else None,
                "time_since_last_trade_seconds": seconds_since,
                # Drawdown Info
                "current_equity_est": dd_state["current_equity"],
                "estimated_peak_equity": dd_state["estimated_peak_equity"],
                "drawdown_abs": dd_state["drawdown_abs"],
                "drawdown_pct": dd_state["drawdown_pct"],
                "max_intraday_drawdown": dd_state["max_intraday_drawdown"],
            }
        )

        # ---- Reasoning ----
        if sig.signal_type == SignalType.ENTER:
            sig.metadata["reason"] = "trend_up_confirmed"
        elif sig.signal_type == SignalType.EXIT:
            sig.metadata["reason"] = "trend_down_confirmed"
        else:
            sig.metadata.setdefault("reason", "trend_hold")

        return sig
