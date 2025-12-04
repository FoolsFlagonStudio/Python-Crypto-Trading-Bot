# bot/strategies/indicators/moving_averages.py

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional


def sma(values: Sequence[float], window: int) -> Optional[float]:
    """
    Simple Moving Average (SMA).

    Parameters
    ----------
    values : sequence of floats
        Recent price values (e.g. closes). Can be list, deque, etc.
        Must be ordered from oldest -> newest or at least consistent.
    window : int
        Lookback window size.

    Returns
    -------
    float | None
        The SMA over the last `window` values, or None if insufficient data.
    """
    if window <= 0:
        raise ValueError("window must be positive")


    if not isinstance(values, list):
            values = list(values)
            
    if len(values) < window:
        return None

    # Use only the last `window` items
    subset = values[-window:]
    return float(sum(subset) / window)


def ema(
    values: Sequence[float],
    window: int,
    prev_ema: Optional[float] = None,
) -> Optional[float]:
    """
    Exponential Moving Average (EMA) with optional previous EMA.

    Designed to be streaming-friendly:
      - If `prev_ema` is provided, only the latest value is used.
      - If `prev_ema` is None, we bootstrap EMA from SMA over the first
        `window` values, then iterate through remaining values.

    Parameters
    ----------
    values : sequence of floats
        Recent price values, ordered oldest -> newest.
    window : int
        EMA period (e.g. 9, 21, 50).
    prev_ema : float | None
        Previous EMA value. If None, will be computed from history.

    Returns
    -------
    float | None
        Latest EMA value, or None if insufficient history.
    """
    if window <= 0:
        raise ValueError("window must be positive")

    if not isinstance(values, list):
        values = list(values)

    n = len(values)
    if n == 0:
        return None

    alpha = 2.0 / (window + 1.0)

    # Not enough data to even bootstrap
    if prev_ema is None and n < window:
        return None

    # If we already have an EMA, update using only the latest price.
    if prev_ema is not None:
        latest_price = float(values[-1])
        return float((latest_price - prev_ema) * alpha + prev_ema)

    # Otherwise, bootstrap EMA from SMA of first `window` points.
    # values: [v0, v1, ..., v_{n-1}]
    # 1) Compute SMA of first `window` values as initial EMA.
    initial_sma = sum(values[:window]) / window
    ema_val = float(initial_sma)

    # 2) Apply EMA update for remaining values.
    for price in values[window:]:
        price = float(price)
        ema_val = (price - ema_val) * alpha + ema_val

    return float(ema_val)
