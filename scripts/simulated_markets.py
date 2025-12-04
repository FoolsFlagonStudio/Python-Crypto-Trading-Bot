# scripts/simulated_markets.py

from __future__ import annotations
import random
from datetime import datetime, timedelta, timezone


class TestCandle:
    def __init__(self, open_, close_, timestamp, high=None, low=None):
        self.open = open_
        self.close = close_
        self.high = high if high is not None else max(open_, close_)
        self.low = low if low is not None else min(open_, close_)
        self.timestamp = timestamp


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def _noise(level=1.5):
    return random.uniform(-level, level)


def _make_candles(prices, start_ts):
    # Convert list of prices → list of TestCandle
    candles = []
    ts = start_ts
    for i in range(1, len(prices)):
        o = prices[i - 1]
        c = prices[i]
        h = max(o, c) + abs(_noise(0.6))
        l = min(o, c) - abs(_noise(0.6))
        candles.append(TestCandle(o, c, ts, h, l))
        ts += timedelta(minutes=1)
    return candles


# --------------------------------------------------------------------
# Scenario 1: Strong Uptrend
# --------------------------------------------------------------------
def generate_uptrend(n=120, start=100):
    prices = []
    price = start
    for _ in range(n):
        price += random.uniform(0.2, 0.8) + _noise()
        prices.append(price)
    return _make_candles(prices, datetime.now(timezone.utc))


# --------------------------------------------------------------------
# Scenario 2: Strong Downtrend
# --------------------------------------------------------------------
def generate_downtrend(n=120, start=100):
    prices = []
    price = start
    for _ in range(n):
        price -= random.uniform(0.2, 0.8) + _noise()
        prices.append(price)
    return _make_candles(prices, datetime.now(timezone.utc))


# --------------------------------------------------------------------
# Scenario 3: Rangebound Market (Mean-Reversion Heaven)
# --------------------------------------------------------------------
def generate_range(n=120, center=100, width=5):
    prices = []
    price = center
    for _ in range(n):
        price += random.uniform(-width, width) * 0.15 + _noise(0.3)
        prices.append(price)
    return _make_candles(prices, datetime.now(timezone.utc))


# --------------------------------------------------------------------
# Scenario 4: Breakout Up
# --------------------------------------------------------------------
def generate_breakout_up(n=120, start=100):
    prices = []
    price = start

    # Consolidation
    for _ in range(n // 2):
        price += _noise(0.5)
        prices.append(price)

    # Strong breakout
    for _ in range(n // 2, n):
        price += random.uniform(0.8, 1.5)
        prices.append(price)

    return _make_candles(prices, datetime.now(timezone.utc))


# --------------------------------------------------------------------
# Scenario 5: Breakout Down
# --------------------------------------------------------------------
def generate_breakout_down(n=120, start=100):
    prices = []
    price = start

    # Consolidation
    for _ in range(n // 2):
        price += _noise(0.5)
        prices.append(price)

    # Breakdown
    for _ in range(n // 2, n):
        price -= random.uniform(0.8, 1.5)
        prices.append(price)

    return _make_candles(prices, datetime.now(timezone.utc))


# --------------------------------------------------------------------
# Scenario 6: Support & Resistance Bounces
# --------------------------------------------------------------------
def generate_support_resistance(n=120, support=95, resistance=105, start=100):
    prices = []
    price = start

    for i in range(n):
        price += _noise(1)

        # Bounce off support
        if price < support:
            price = support + random.uniform(0.5, 1.5)

        # Reject off resistance
        if price > resistance:
            price = resistance - random.uniform(0.5, 1.5)

        prices.append(price)

    return _make_candles(prices, datetime.now(timezone.utc))


# --------------------------------------------------------------------
# Scenario 7: High Volatility / Whipsaw
# --------------------------------------------------------------------
def generate_high_vol(n=120, start=100):
    prices = []
    price = start

    for _ in range(n):
        price += random.uniform(-3.5, 3.5)  # big noise
        prices.append(price)

    return _make_candles(prices, datetime.now(timezone.utc))


# --------------------------------------------------------------------
# Scenario Router
# --------------------------------------------------------------------
SCENARIOS = {
    "uptrend": generate_uptrend,
    "downtrend": generate_downtrend,
    "range": generate_range,
    "breakout_up": generate_breakout_up,
    "breakout_down": generate_breakout_down,
    "sr": generate_support_resistance,
    "high_vol": generate_high_vol,
    "random": lambda n=120: generate_range(n)  # default fallback
}
