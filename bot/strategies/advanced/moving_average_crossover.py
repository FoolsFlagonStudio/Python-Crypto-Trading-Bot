# bot/strategies/advanced/moving_average_crossover.py

from __future__ import annotations

from collections import deque
from typing import Optional

from bot.strategies.base import Strategy
from bot.strategies.signals import StrategySignal, SignalType
from bot.strategies.indicators.moving_averages import ema
from bot.strategies.portfolio_metrics import (
    compute_unrealized_pnl,
    compute_last_trade_info,
    compute_drawdown_status,
)
from bot.core.logger import get_logger

logger = get_logger(__name__)


class MovingAverageCrossoverStrategy(Strategy):
    """
    Classic moving average crossover strategy with expanded analytics.

    Indicators:
      - fast EMA
      - slow EMA

    Entry:
      - Bullish crossover: fast EMA crosses ABOVE slow EMA.

    Exit:
      - Bearish crossover: fast EMA crosses BELOW slow EMA.

    Metadata includes:
      - Unrealized P/L
      - Drawdown status
      - Last entry price
      - Time since last trade
      - Rolling EMAs
      - Volatility-ready fields for future use
    """

    def __init__(self, params: dict | None = None):
        super().__init__(params)

        self.fast_window: int = int(self.params.get("fast_window", 9))
        self.slow_window: int = int(self.params.get("slow_window", 21))
        self.buffer_pct: float = float(self.params.get("buffer_pct", 0.0))

        if self.fast_window >= self.slow_window:
            logger.warning("Fast EMA >= Slow EMA — unusual configuration.")

        max_history: int = int(
            self.params.get("max_history", max(
                self.fast_window, self.slow_window) * 4)
        )

        # Rolling price buffer
        self.closes = deque(maxlen=max_history)

        # EMA states
        self.fast_ema: Optional[float] = None
        self.slow_ema: Optional[float] = None
        self.prev_fast_ema: Optional[float] = None
        self.prev_slow_ema: Optional[float] = None

    # ------------------------------------------------------------------
    # Indicator Updates
    # ------------------------------------------------------------------

    def _update_indicators(self, candle) -> None:
        price = float(candle.close)
        self.closes.append(price)

        # Shift previous values
        self.prev_fast_ema = self.fast_ema
        self.prev_slow_ema = self.slow_ema

        # Streaming EMA updates
        self.fast_ema = ema(self.closes, self.fast_window,
                            prev_ema=self.fast_ema)
        self.slow_ema = ema(self.closes, self.slow_window,
                            prev_ema=self.slow_ema)

    def _has_enough_data(self) -> bool:
        return (
            self.fast_ema is not None
            and self.slow_ema is not None
            and self.prev_fast_ema is not None
            and self.prev_slow_ema is not None
        )

    # ------------------------------------------------------------------
    # Crossover Logic
    # ------------------------------------------------------------------

    def _bullish_crossover(self) -> bool:
        if not self._has_enough_data():
            return False

        was_below_or_equal = self.prev_fast_ema <= self.prev_slow_ema
        threshold = 1.0 + self.buffer_pct
        is_above_now = self.fast_ema > self.slow_ema * threshold

        return was_below_or_equal and is_above_now

    def _bearish_crossover(self) -> bool:
        if not self._has_enough_data():
            return False

        was_above_or_equal = self.prev_fast_ema >= self.prev_slow_ema
        threshold = 1.0 - self.buffer_pct
        is_below_now = self.fast_ema < self.slow_ema * threshold

        return was_above_or_equal and is_below_now

    # ------------------------------------------------------------------
    # Strategy Decisions
    # ------------------------------------------------------------------

    def should_enter(self, candle, portfolio_state) -> bool:
        self._update_indicators(candle)

        if self._bullish_crossover():
            logger.info("[MA_XOVER] ENTER signal detected")
            return True

        return False

    def should_exit(self, candle, portfolio_state) -> bool:
        # ensure indicators updated even if runner calls exit first
        if self.fast_ema is None:
            self._update_indicators(candle)

        if self._bearish_crossover():
            logger.info("[MA_XOVER] EXIT signal detected")
            return True

        return False

    # ------------------------------------------------------------------
    # Enriched Metadata
    # ------------------------------------------------------------------

    def generate_signal(self, candle, portfolio_state) -> StrategySignal:
        sig = super().generate_signal(candle, portfolio_state)

        if sig.metadata is None:
            sig.metadata = {}

        price = float(candle.close)

        # ---- Portfolio Metrics ----
        unrealized = compute_unrealized_pnl(portfolio_state, price)
        last_entry, opened_at, seconds_since = compute_last_trade_info(
            portfolio_state)
        dd = compute_drawdown_status(
            portfolio_state, unrealized_pnl=unrealized)

        sig.metadata.update(
            {
                # Strategy Info
                "strategy": "moving_average_crossover",
                "fast_window": self.fast_window,
                "slow_window": self.slow_window,
                "buffer_pct": self.buffer_pct,
                # Indicator Context
                "fast_ema": self.fast_ema,
                "slow_ema": self.slow_ema,
                "prev_fast_ema": self.prev_fast_ema,
                "prev_slow_ema": self.prev_slow_ema,
                "price": price,
                # Trade Context
                "unrealized_pnl": unrealized,
                "last_entry_price": last_entry,
                "last_trade_opened_at": opened_at.isoformat() if opened_at else None,
                "time_since_last_trade_seconds": seconds_since,
                # Drawdown Context
                "current_equity_est": dd["current_equity"],
                "estimated_peak_equity": dd["estimated_peak_equity"],
                "drawdown_abs": dd["drawdown_abs"],
                "drawdown_pct": dd["drawdown_pct"],
                "max_intraday_drawdown": dd["max_intraday_drawdown"],
            }
        )

        # Refine reason
        if sig.signal_type == SignalType.ENTER:
            sig.metadata["reason"] = "bullish_ma_crossover"
        elif sig.signal_type == SignalType.EXIT:
            sig.metadata["reason"] = "bearish_ma_crossover"
        else:
            sig.metadata.setdefault("reason", "ma_hold")

        return sig
