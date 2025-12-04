# bot/strategies/indicators/support_resistance.py

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional, Tuple


# ----------------------------------------------------------------------
# Swing High / Swing Low detection
# ----------------------------------------------------------------------
def is_swing_high(values: Sequence[float], index: int, left: int, right: int) -> bool:
    """
    A swing high occurs when the candle at `index` is higher than
    all candles in the `left` bars before and `right` bars after.

    This function assumes `values` are ordered oldest -> newest.
    """
    if index - left < 0 or index + right >= len(values):
        return False

    pivot = values[index]

    for i in range(index - left, index + right + 1):
        if i == index:
            continue
        if values[i] >= pivot:
            return False

    return True


def is_swing_low(values: Sequence[float], index: int, left: int, right: int) -> bool:
    """
    A swing low occurs when the candle at `index` is lower than
    all candles in the `left` bars before and `right` bars after.
    """
    if index - left < 0 or index + right >= len(values):
        return False

    pivot = values[index]

    for i in range(index - left, index + right + 1):
        if i == index:
            continue
        if values[i] <= pivot:
            return False

    return True


# ----------------------------------------------------------------------
# Rolling Support & Resistance Levels
# ----------------------------------------------------------------------
def find_support_resistance(
    highs: Sequence[float],
    lows: Sequence[float],
    left: int = 3,
    right: int = 3,
    lookback: int = 100,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Scan recent candles to identify latest support and resistance zones
    using swing-high / swing-low logic.

    Parameters
    ----------
    highs, lows : sequence of floats, ordered oldest -> newest.
    left, right : int
        Number of candles on each side required to confirm swing points.
    lookback : int
        Max number of candles to scan backward from the end.

    Returns
    -------
    (support_level, resistance_level)
    """
    n = len(highs)
    if n < left + right + 1:
        return None, None

    start = max(0, n - lookback)

    support = None
    resistance = None

    # Walk backwards from the most recent candle
    for i in range(n - 1, start - 1, -1):
        if resistance is None and is_swing_high(highs, i, left, right):
            resistance = highs[i]

        if support is None and is_swing_low(lows, i, left, right):
            support = lows[i]

        if support is not None and resistance is not None:
            break

    return support, resistance


# ----------------------------------------------------------------------
# Support/Resistance proximity checks
# ----------------------------------------------------------------------
def near_level(
    price: float,
    level: Optional[float],
    tolerance_pct: float = 0.005,  # 0.5% default
) -> bool:
    """
    Check if price is within ± tolerance_pct of a given level.
    """
    if level is None:
        return False

    if level == 0:
        return False

    diff = abs(price - level) / level
    return diff <= tolerance_pct


def bounce_from_support(
    close: float,
    prev_close: float,
    support: Optional[float],
    tolerance_pct: float = 0.005,
) -> bool:
    """
    Detect a bounce off support:
      - price dips near support then rises
    """
    if support is None:
        return False

    # previous candle near support AND current candle rising
    return (
        near_level(prev_close, support, tolerance_pct)
        and close > prev_close
    )


def reject_from_resistance(
    close: float,
    prev_close: float,
    resistance: Optional[float],
    tolerance_pct: float = 0.005,
) -> bool:
    """
    Detect a rejection off resistance:
      - price tests resistance then falls
    """
    if resistance is None:
        return False

    return (
        near_level(prev_close, resistance, tolerance_pct)
        and close < prev_close
    )
