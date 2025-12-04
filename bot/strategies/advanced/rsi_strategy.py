# bot/strategies/advanced/rsi_strategy.py

from __future__ import annotations

from collections import deque
from typing import Optional

from bot.strategies.base import Strategy
from bot.strategies.signals import StrategySignal, SignalType
from bot.strategies.indicators.rsi import rsi
from bot.strategies.indicators.volatility import volatility_stddev
from bot.strategies.portfolio_metrics import (
    compute_unrealized_pnl,
    compute_last_trade_info,
    compute_drawdown_status,
)
from bot.core.logger import get_logger

logger = get_logger(__name__)


class RSIStrategy(Strategy):
    """
    RSI Oversold/Overbought Mean Reversion Strategy.

    Entry:
      - Buy when RSI < lower_threshold  (oversold)

    Exit:
      - Sell when RSI > upper_threshold (overbought)

    Metadata includes:
      - Unrealized P/L
      - Rolling RSI values
      - Volatility metrics
      - Last entry price
      - Time since last trade
      - Drawdown info
    """

    def __init__(self, params: dict | None = None):
        super().__init__(params)

        # RSI parameters
        self.period = int(self.params.get("period", 14))
        self.lower = float(self.params.get("lower", 30.0))
        self.upper = float(self.params.get("upper", 70.0))

        # volatility options
        self.use_volatility = bool(self.params.get("use_volatility", False))
        self.vol_window = int(self.params.get("vol_window", 20))
        self.vol_mult = float(self.params.get("vol_mult", 1.0))

        max_history = int(self.params.get("max_history", self.period * 4))

        self.closes = deque(maxlen=max_history)

        # Indicator state
        self.rsi_val: Optional[float] = None
        self.volatility: Optional[float] = None

    # -------------------------------------------------------------------------
    # RSI / volatility calculation
    # -------------------------------------------------------------------------

    def _update_indicators(self) -> None:
        # Not enough data to compute RSI
        if len(self.closes) < self.period:
            self.rsi_val = None
            self.prev_avg_gain = None
            self.prev_avg_loss = None
            self.volatility = None
            return

        arr = list(self.closes)

        # Get RSI result (may return None or a tuple)
        result = rsi(
            arr,
            self.period,
            prev_avg_gain=self.prev_avg_gain,
            prev_avg_loss=self.prev_avg_loss,
        )

        if result is None:
            self.rsi_val = None
            return

        # Unpack tuple from RSI indicator
        rsi_val, avg_gain, avg_loss = result

        self.rsi_val = float(rsi_val)
        self.prev_avg_gain = float(avg_gain)
        self.prev_avg_loss = float(avg_loss)

        # Volatility (optional)
        if self.use_volatility:
            self.volatility = volatility_stddev(arr, self.vol_window)
        else:
            self.volatility = None

    def _has_enough_data(self) -> bool:
        return self.rsi_val is not None

    # -------------------------------------------------------------------------
    # Strategy logic
    # -------------------------------------------------------------------------

    def should_enter(self, candle, portfolio_state) -> bool:
        close = float(candle.close)
        self.closes.append(close)

        self._update_indicators()

        if not self._has_enough_data():
            return False

        # Oversold → enter long
        if self.rsi_val < self.lower:
            logger.info(
                "[RSI] ENTER oversold: RSI=%.2f < lower=%.2f",
                self.rsi_val,
                self.lower,
            )
            return True

        return False

    def should_exit(self, candle, portfolio_state) -> bool:
        close = float(candle.close)

        # Ensure we have enough price history
        if len(self.closes) == 0:
            self.closes.append(close)
            return False

        self.closes.append(close)
        self._update_indicators()

        if not self._has_enough_data():
            return False

        # Overbought → exit
        if self.rsi_val > self.upper:
            logger.info(
                "[RSI] EXIT overbought: RSI=%.2f > upper=%.2f",
                self.rsi_val,
                self.upper,
            )
            return True

        return False

    # -------------------------------------------------------------------------
    # Enriched Metadata
    # -------------------------------------------------------------------------

    def generate_signal(self, candle, portfolio_state) -> StrategySignal:
        sig = super().generate_signal(candle, portfolio_state)

        if sig.metadata is None:
            sig.metadata = {}

        price = float(candle.close)

        # ---- Portfolio Metrics ----
        unrealized = compute_unrealized_pnl(portfolio_state, price)
        last_entry_price, opened_at, seconds_since_last = compute_last_trade_info(
            portfolio_state
        )
        dd_state = compute_drawdown_status(
            portfolio_state,
            unrealized_pnl=unrealized,
        )

        # ---- Rolling Indicator Exports ----
        sig.metadata.update(
            {
                "strategy": "rsi",
                "period": self.period,
                "lower_threshold": self.lower,
                "upper_threshold": self.upper,
                "rsi": self.rsi_val,
                "use_volatility": self.use_volatility,
                "volatility": self.volatility,
                "vol_window": self.vol_window,
                "vol_mult": self.vol_mult,
                # Portfolio & Risk Info
                "unrealized_pnl": unrealized,
                "last_entry_price": last_entry_price,
                "last_trade_opened_at": opened_at.isoformat() if opened_at else None,
                "time_since_last_trade_seconds": seconds_since_last,
                # Drawdown Info
                "current_equity_est": dd_state["current_equity"],
                "estimated_peak_equity": dd_state["estimated_peak_equity"],
                "drawdown_abs": dd_state["drawdown_abs"],
                "drawdown_pct": dd_state["drawdown_pct"],
                "max_intraday_drawdown": dd_state["max_intraday_drawdown"],
            }
        )

        # ---- Signal Reason ----
        if sig.signal_type == SignalType.ENTER:
            sig.metadata["reason"] = "rsi_oversold_entry"
        elif sig.signal_type == SignalType.EXIT:
            sig.metadata["reason"] = "rsi_overbought_exit"
        else:
            sig.metadata.setdefault("reason", "rsi_hold")

        return sig
