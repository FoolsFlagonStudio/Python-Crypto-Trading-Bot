# bot/strategies/advanced/breakout.py

from __future__ import annotations

from collections import deque
from typing import Optional

from bot.strategies.base import Strategy
from bot.strategies.signals import StrategySignal, SignalType
from bot.strategies.indicators.volatility import atr
from bot.strategies.portfolio_metrics import (
    compute_unrealized_pnl,
    compute_last_trade_info,
    compute_drawdown_status,
)
from bot.core.logger import get_logger

logger = get_logger(__name__)


class BreakoutStrategy(Strategy):
    """
    Breakout strategy using highest-high & lowest-low lookback levels.

    Entry:
      - Price breaks ABOVE highest-high + buffer

    Exit:
      - Price breaks BELOW lowest-low - buffer

    Buffers:
      - ATR * atr_mult   (recommended)
      - OR % buffer

    Metadata:
      - Unrealized P/L
      - ATR values
      - Highest/lowest lookback levels
      - Last entry price / time since last trade
      - Drawdown snapshot
    """

    def __init__(self, params: dict | None = None):
        super().__init__(params)

        self.lookback = int(self.params.get("lookback", 20))
        self.use_atr = bool(self.params.get("use_atr", True))
        self.atr_period = int(self.params.get("atr_period", 14))
        self.atr_mult = float(self.params.get("atr_mult", 1.0))
        self.buffer_pct = float(self.params.get("buffer_pct", 0.0))

        max_history = int(self.params.get("max_history", self.lookback * 4))

        self.highs = deque(maxlen=max_history)
        self.lows = deque(maxlen=max_history)
        self.closes = deque(maxlen=max_history)

        self.atr_val: Optional[float] = None

        if self.lookback <= 0:
            raise ValueError("lookback must be positive")

    # ----------------------------------------------------------------------
    # Indicator Updates
    # ----------------------------------------------------------------------

    def _update_indicators(self, candle):
        self.highs.append(float(candle.high))
        self.lows.append(float(candle.low))
        self.closes.append(float(candle.close))

        self.atr_val = atr(
            self.highs,
            self.lows,
            self.closes,
            period=self.atr_period,
            prev_atr=self.atr_val,
        )

    def _has_enough_data(self):
        return len(self.closes) >= self.lookback

    # ----------------------------------------------------------------------
    # Breakout Helpers
    # ----------------------------------------------------------------------

    def _highest_high(self):
        arr = list(self.highs)
        if len(arr) < self.lookback:
            return None
        return max(arr[-self.lookback:])  


    def _lowest_low(self):
        arr = list(self.lows)
        if len(arr) < self.lookback:
            return None
        return min(arr[-self.lookback:]) 

    def _breakout_up(self):
        if not self._has_enough_data():
            return False

        close = self.closes[-1]
        level = self._highest_high()

        buffer = 0.0
        if self.use_atr and self.atr_val:
            buffer = self.atr_val * self.atr_mult
        elif self.buffer_pct:
            buffer = level * self.buffer_pct

        return close > (level + buffer)

    def _breakout_down(self):
        if not self._has_enough_data():
            return False

        close = self.closes[-1]
        level = self._lowest_low()

        buffer = 0.0
        if self.use_atr and self.atr_val:
            buffer = self.atr_val * self.atr_mult
        elif self.buffer_pct:
            buffer = level * self.buffer_pct

        return close < (level - buffer)

    # ----------------------------------------------------------------------
    # Strategy Logic
    # ----------------------------------------------------------------------

    def should_enter(self, candle, portfolio_state):
        self._update_indicators(candle)

        if self._breakout_up():
            logger.info(
                "[BREAKOUT] ENTER breakout_up level=%.2f close=%.2f",
                self._highest_high(),
                self.closes[-1],
            )
            return True

        return False

    def should_exit(self, candle, portfolio_state):
        if len(self.closes) == 0:
            self._update_indicators(candle)
            return False

        self._update_indicators(candle)

        if self._breakout_down():
            logger.info(
                "[BREAKOUT] EXIT breakout_down level=%.2f close=%.2f",
                self._lowest_low(),
                self.closes[-1],
            )
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
        last_entry_price, opened_at, sec_since = compute_last_trade_info(
            portfolio_state
        )
        dd_state = compute_drawdown_status(
            portfolio_state,
            unrealized_pnl=unrealized,
        )

        # ---- Indicator Context ----
        highest = self._highest_high() if self._has_enough_data() else None
        lowest = self._lowest_low() if self._has_enough_data() else None

        sig.metadata.update(
            {
                "strategy": "breakout",
                "lookback": self.lookback,
                "highest_high": highest,
                "lowest_low": lowest,
                "atr": self.atr_val,
                "atr_period": self.atr_period,
                "atr_mult": self.atr_mult,
                "buffer_pct": self.buffer_pct,
                # Portfolio + Risk
                "unrealized_pnl": unrealized,
                "last_entry_price": last_entry_price,
                "last_trade_opened_at": opened_at.isoformat() if opened_at else None,
                "time_since_last_trade_seconds": sec_since,
                # Drawdown
                "current_equity_est": dd_state["current_equity"],
                "estimated_peak_equity": dd_state["estimated_peak_equity"],
                "drawdown_abs": dd_state["drawdown_abs"],
                "drawdown_pct": dd_state["drawdown_pct"],
                "max_intraday_drawdown": dd_state["max_intraday_drawdown"],
                # Last Close
                "close": price,
            }
        )

        # ---- Reasoning ----
        if sig.signal_type == SignalType.ENTER:
            sig.metadata["reason"] = "breakout_up"
        elif sig.signal_type == SignalType.EXIT:
            sig.metadata["reason"] = "breakout_down"
        else:
            sig.metadata.setdefault("reason", "breakout_hold")

        return sig
