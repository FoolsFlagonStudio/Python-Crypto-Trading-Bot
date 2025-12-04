# bot/strategies/advanced/support_resistance_strategy.py

from __future__ import annotations

from collections import deque
from typing import Optional

from bot.strategies.base import Strategy
from bot.strategies.signals import StrategySignal, SignalType
from bot.strategies.indicators.support_resistance import (
    find_support_resistance,
    bounce_from_support,
    reject_from_resistance,
)
from bot.strategies.portfolio_metrics import (
    compute_unrealized_pnl,
    compute_last_trade_info,
    compute_drawdown_status,
)
from bot.core.logger import get_logger

logger = get_logger(__name__)


class SupportResistanceStrategy(Strategy):
    """
    Support/Resistance bounce & rejection strategy.

    Entry:
      - Bounce from support: price near support then rising

    Exit:
      - Rejection from resistance: price near resistance then falling

    Metadata:
      - Support & resistance levels
      - Unrealized P/L
      - Last entry price & timing
      - Drawdown stats
      - Volatility-ready structure
    """

    def __init__(self, params: dict | None = None):
        super().__init__(params)

        self.left = int(self.params.get("left", 3))
        self.right = int(self.params.get("right", 3))
        self.lookback = int(self.params.get("lookback", 100))
        self.tolerance_pct = float(self.params.get("tolerance_pct", 0.005))

        max_history = int(self.params.get("max_history", self.lookback * 2))

        self.highs = deque(maxlen=max_history)
        self.lows = deque(maxlen=max_history)
        self.closes = deque(maxlen=max_history)

        # Cached S/R levels
        self.support: Optional[float] = None
        self.resistance: Optional[float] = None

    # ---------------------------------------------------------------
    # Support/Resistance Updates
    # ---------------------------------------------------------------

    def _update_levels(self) -> None:
        self.support, self.resistance = find_support_resistance(
            highs=self.highs,
            lows=self.lows,
            left=self.left,
            right=self.right,
            lookback=self.lookback,
        )

    # ---------------------------------------------------------------
    # Strategy Logic
    # ---------------------------------------------------------------

    def should_enter(self, candle, portfolio_state) -> bool:
        close = float(candle.close)

        self.highs.append(float(candle.high))
        self.lows.append(float(candle.low))
        self.closes.append(close)

        if len(self.closes) < 2:
            return False

        self._update_levels()

        prev_close = self.closes[-2]

        # Entry: bounce from support
        if bounce_from_support(
            close=close,
            prev_close=prev_close,
            support=self.support,
            tolerance_pct=self.tolerance_pct,
        ):
            logger.info(
                "[SUPPORT] ENTER bounce @ %.2f (support=%.2f)",
                close,
                self.support if self.support else float("nan"),
            )
            return True

        return False

    def should_exit(self, candle, portfolio_state) -> bool:
        close = float(candle.close)

        if len(self.closes) == 0:
            self.highs.append(float(candle.high))
            self.lows.append(float(candle.low))
            self.closes.append(close)
            return False

        self.highs.append(float(candle.high))
        self.lows.append(float(candle.low))
        self.closes.append(close)

        self._update_levels()

        prev_close = self.closes[-2]

        # Exit: rejection from resistance
        if reject_from_resistance(
            close=close,
            prev_close=prev_close,
            resistance=self.resistance,
            tolerance_pct=self.tolerance_pct,
        ):
            logger.info(
                "[RESISTANCE] EXIT rejection @ %.2f (resistance=%.2f)",
                close,
                self.resistance if self.resistance else float("nan"),
            )
            return True

        return False

    # ---------------------------------------------------------------
    # Enriched Metadata
    # ---------------------------------------------------------------

    def generate_signal(self, candle, portfolio_state) -> StrategySignal:
        sig = super().generate_signal(candle, portfolio_state)

        if sig.metadata is None:
            sig.metadata = {}

        price = float(candle.close)

        # ---- Portfolio & Risk Metrics ----
        unrealized = compute_unrealized_pnl(portfolio_state, price)
        last_entry_price, opened_at, seconds_since = compute_last_trade_info(
            portfolio_state
        )
        dd = compute_drawdown_status(
            portfolio_state,
            unrealized_pnl=unrealized,
        )

        # ---- Strategy-Specific Metadata ----
        sig.metadata.update(
            {
                "strategy": "support_resistance",
                "left": self.left,
                "right": self.right,
                "lookback": self.lookback,
                "tolerance_pct": self.tolerance_pct,
                "support": self.support,
                "resistance": self.resistance,
                "last_close": price,
                # Portfolio Metrics
                "unrealized_pnl": unrealized,
                "last_entry_price": last_entry_price,
                "last_trade_opened_at": opened_at.isoformat() if opened_at else None,
                "time_since_last_trade_seconds": seconds_since,
                # Drawdown Metrics
                "current_equity_est": dd["current_equity"],
                "estimated_peak_equity": dd["estimated_peak_equity"],
                "drawdown_abs": dd["drawdown_abs"],
                "drawdown_pct": dd["drawdown_pct"],
                "max_intraday_drawdown": dd["max_intraday_drawdown"],
            }
        )

        # ---- Signal Reasoning ----
        if sig.signal_type == SignalType.ENTER:
            sig.metadata["reason"] = "bounce_from_support"
        elif sig.signal_type == SignalType.EXIT:
            sig.metadata["reason"] = "reject_from_resistance"
        else:
            sig.metadata.setdefault("reason", "sr_hold")

        return sig
