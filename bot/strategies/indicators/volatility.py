# bot/strategies/indicators/volatility.py

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional, Tuple
import math


# -----------------------------------------------------------
# True Range (TR)
# -----------------------------------------------------------
def true_range(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> Optional[float]:
    """
    Compute the True Range for the most recent candle.

    TR = max(
        high - low,
        abs(high - previous_close),
        abs(low - previous_close)
    )

    Requires at least 2 data points (previous close).
    """
    n = len(highs)
    if n < 2:
        return None

    high = float(highs[-1])
    low = float(lows[-1])
    prev_close = float(closes[-2])

    return max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close),
    )


# -----------------------------------------------------------
# ATR (Average True Range) - Wilder's smoothing
# -----------------------------------------------------------
def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
    prev_atr: Optional[float] = None,
) -> Optional[float]:
    """
    Compute ATR (Average True Range).

    Two modes:
    1) Bootstrap: if prev_atr is None, compute ATR over first `period` TRs.
    2) Streaming: if prev_atr exists, update with Wilder's smoothing.

    Returns
    -------
    float or None
    """
    n = len(highs)
    if n < period + 1:  # Need period TR's + 1 previous close
        return None

    # Compute the latest True Range
    tr = true_range(highs, lows, closes)
    if tr is None:
        return None

    # Streaming update
    if prev_atr is not None:
        # Wilder's smoothing:
        # ATR_t = (prev_ATR * (period - 1) + TR_t) / period
        new_atr = (prev_atr * (period - 1) + tr) / period
        return float(new_atr)

    # Bootstrap ATR using first `period` TRs
    trs = []
    # TRs computed from candle 1..period
    for i in range(1, period + 1):
        tr_i = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(float(tr_i))

    initial_atr = sum(trs) / period
    return float(initial_atr)


# -----------------------------------------------------------
# Standard Deviation of Log Returns (Volatility)
# -----------------------------------------------------------
def volatility_stddev(
    closes: Sequence[float],
    window: int,
) -> Optional[float]:
    """
    Compute rolling standard deviation of log returns:
        vol = stddev( ln(close_t / close_{t-1}) )

    This is very common for:
        - volatility breakout strategies
        - risk metrics
        - adaptive stop sizing
        - trend filters

    Returns None if insufficient data.
    """
    n = len(closes)
    if n < window + 1:
        return None

    # Compute log returns on last `window` periods
    returns = []
    for i in range(n - window, n):
        prev = float(closes[i - 1])
        curr = float(closes[i])
        if prev <= 0:
            return None
        log_ret = math.log(curr / prev)
        returns.append(log_ret)

    # Standard deviation
    mean_ret = sum(returns) / len(returns)
    variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
    return float(math.sqrt(variance))
