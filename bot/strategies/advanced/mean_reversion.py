# bot/strategies/advanced/mean_reversion.py

from __future__ import annotations

from collections import deque
from typing import Optional

from bot.strategies.base import Strategy
from bot.strategies.signals import StrategySignal, SignalType
from bot.strategies.indicators.moving_averages import sma
from bot.strategies.indicators.volatility import volatility_stddev
from bot.strategies.portfolio_metrics import (
    compute_unrealized_pnl,
    compute_last_trade_info,
    compute_drawdown_status,
)
from bot.core.logger import get_logger

logger = get_logger(__name__)


class MeanReversionStrategy(Strategy):
    """
    Mean Reversion Strategy (Buy Low, Sell High).

    Core logic:
      - When price falls below rolling SMA by a certain % threshold → ENTER (buy)
      - When price reverts back toward SMA or rises above it → EXIT (sell)

    Optional enhancements supported:
      - Volatility filter (stddev on returns)
      - Custom lookback for SMA
      - Custom deviation threshold

    Parameters:
      - lookback: int            # SMA window (default: 20)
      - threshold_pct: float     # deviation threshold (default: 0.01 = 1%)
      - use_volatility: bool     # enable volatility filter
      - vol_window: int          # window for stddev volatility
      - vol_mult: float          # multiplier to scale threshold based on vol
      - max_history: int         # strategy rolling history size
    """

    def __init__(self, params: dict | None = None):
        super().__init__(params)

        self.lookback = int(self.params.get("lookback", 20))
        self.threshold_pct = float(
            self.params.get("threshold_pct", 0.01))  # 1%

        # Volatility filter
        self.use_volatility = bool(self.params.get("use_volatility", False))
        self.vol_window = int(self.params.get("vol_window", 20))
        self.vol_mult = float(self.params.get("vol_mult", 1.0))

        max_history = int(self.params.get("max_history", self.lookback * 4))

        self.closes = deque(maxlen=max_history)

        # Computed each candle
        self.mean: Optional[float] = None
        self.deviation: Optional[float] = None
        self.volatility: Optional[float] = None

        if self.lookback <= 0:
            raise ValueError("lookback must be positive")

    # ----------------------------------------------------------------------
    # Internal calculation helpers
    # ----------------------------------------------------------------------

    def _update_indicators(self) -> None:
        """
        Compute rolling SMA, deviation, and optional volatility.
        """
        if len(self.closes) < self.lookback:
            self.mean = None
            self.deviation = None
            self.volatility = None
            return

        close = self.closes[-1]
        mean = sma(self.closes, self.lookback)

        if mean is None:
            self.mean = None
            self.deviation = None
            self.volatility = None
            return

        self.mean = mean
        self.deviation = (close - mean) / mean  # fractional deviation

        # volatility (optional)
        if self.use_volatility:
            vol = volatility_stddev(self.closes, self.vol_window)
            self.volatility = vol
        else:
            self.volatility = None

    def _has_enough_data(self) -> bool:
        return self.mean is not None

    # ----------------------------------------------------------------------
    # Strategy logic
    # ----------------------------------------------------------------------

    def should_enter(self, candle, portfolio_state) -> bool:
        close = float(candle.close)
        self.closes.append(close)

        self._update_indicators()
        if not self._has_enough_data():
            return False

        # Base threshold
        threshold = self.threshold_pct

        # Expand threshold based on volatility, if enabled
        if self.use_volatility and self.volatility is not None:
            threshold = max(threshold, self.volatility * self.vol_mult)

        # Enter when price is significantly BELOW the mean
        if self.deviation < -threshold:
            logger.info(
                "[MEAN_REVERT] ENTER: deviation %.4f < threshold %.4f (close=%.2f mean=%.2f)",
                self.deviation,
                threshold,
                close,
                self.mean,
            )
            return True

        return False

    def should_exit(self, candle, portfolio_state) -> bool:
        close = float(candle.close)

        # If no price history yet, append and skip exit
        if len(self.closes) == 0:
            self.closes.append(close)
            return False

        self.closes.append(close)
        self._update_indicators()

        if not self._has_enough_data():
            return False

        threshold = self.threshold_pct
        if self.use_volatility and self.volatility is not None:
            threshold = max(threshold, self.volatility * self.vol_mult)

        # Exit when price returns near mean or rises above it
        if self.deviation >= -threshold * 0.25:  # near or above mean
            logger.info(
                "[MEAN_REVERT] EXIT: deviation %.4f >= reversion_level (close=%.2f mean=%.2f)",
                self.deviation,
                close,
                self.mean,
            )
            return True

        return False

    # ----------------------------------------------------------------------
    # Metadata: Unrealized P/L, Volatility, Last Trade, Drawdown
    # ----------------------------------------------------------------------

    def generate_signal(self, candle, portfolio_state) -> StrategySignal:
        sig = super().generate_signal(candle, portfolio_state)

        if sig.metadata is None:
            sig.metadata = {}

        price = float(candle.close)

        # --- Portfolio / risk metrics ---
        unrealized = compute_unrealized_pnl(portfolio_state, price)
        last_entry_price, last_opened_at, seconds_since_last = compute_last_trade_info(
            portfolio_state
        )
        dd_status = compute_drawdown_status(
            portfolio_state,
            unrealized_pnl=unrealized,
        )

        # --- Rolling indicator exports (mean reversion context) ---
        sig.metadata.update(
            {
                "strategy": "mean_reversion",
                "lookback": self.lookback,
                "threshold_pct": self.threshold_pct,
                "mean": self.mean,
                "deviation": self.deviation,
                "volatility_enabled": self.use_volatility,
                "volatility": self.volatility,
                "vol_window": self.vol_window,
                "vol_mult": self.vol_mult,
                # Portfolio / P&L metrics
                "unrealized_pnl": unrealized,
                "last_entry_price": last_entry_price,
                "last_trade_opened_at": last_opened_at.isoformat()
                if last_opened_at
                else None,
                "time_since_last_trade_seconds": seconds_since_last,
                # Drawdown snapshot
                "current_equity_est": dd_status["current_equity"],
                "estimated_peak_equity": dd_status["estimated_peak_equity"],
                "drawdown_abs": dd_status["drawdown_abs"],
                "drawdown_pct": dd_status["drawdown_pct"],
                "max_intraday_drawdown": dd_status["max_intraday_drawdown"],
            }
        )

        if sig.signal_type == SignalType.ENTER:
            sig.metadata["reason"] = "price_below_mean_threshold"
        elif sig.signal_type == SignalType.EXIT:
            sig.metadata["reason"] = "mean_reversion_exit"
        else:
            sig.metadata.setdefault("reason", "mean_reversion_hold")

        return sig
