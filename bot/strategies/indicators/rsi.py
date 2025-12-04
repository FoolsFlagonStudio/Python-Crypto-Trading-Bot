# bot/strategies/indicators/rsi.py

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional, Tuple


def _bootstrap_rsi(values: Sequence[float], period: int) -> Optional[Tuple[float, float, float]]:
    """
    Bootstrap RSI by calculating the initial average gain and average loss
    using the first `period` differences.

    Parameters
    ----------
    values : sequence of floats, oldest -> newest
    period : int

    Returns
    -------
    (rsi, avg_gain, avg_loss) or None
    """
    if len(values) <= period:
        return None

    gains = []
    losses = []

    # Calculate changes over the first `period` steps.
    # values: [v0, v1, v2, ..., vN]
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        if delta > 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0, avg_gain, avg_loss  # RSI is maxed

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return float(rsi), float(avg_gain), float(avg_loss)


def rsi(
    values: Sequence[float],
    period: int,
    prev_avg_gain: Optional[float] = None,
    prev_avg_loss: Optional[float] = None,
) -> Optional[Tuple[float, float, float]]:
    """
    Compute RSI (Relative Strength Index) using Wilder's smoothing.

    Supports two modes:
    --------------------------------------
    1) Bootstrap mode:
        If prev_avg_gain and prev_avg_loss are None,
        will compute initial averages from history.

    2) Streaming update:
        If prev_avg_gain and prev_avg_loss are provided,
        only the latest delta is used for EMA-style updates.

    Parameters
    ----------
    values : sequence of floats
        Ordered oldest -> newest. Should include price history.
    period : int
        RSI period, typically 14.
    prev_avg_gain, prev_avg_loss : float or None
        Previous averages for streaming mode.

    Returns
    -------
    (rsi, avg_gain, avg_loss) or None
    """
    n = len(values)
    if n < period + 1:
        return None

    # If we have previous gain/loss, update using only last delta.
    if prev_avg_gain is not None and prev_avg_loss is not None:
        delta = values[-1] - values[-2]

        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)

        avg_gain = (prev_avg_gain * (period - 1) + gain) / period
        avg_loss = (prev_avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            return 100.0, float(avg_gain), float(avg_loss)

        rs = avg_gain / avg_loss
        rsi_val = 100 - (100 / (1 + rs))

        return float(rsi_val), float(avg_gain), float(avg_loss)

    # Otherwise, bootstrap.
    return _bootstrap_rsi(values, period)
