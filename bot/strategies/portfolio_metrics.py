# bot/strategies/portfolio_metrics.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from bot.persistence.db import PortfolioState  # for type hints only


def _to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------
# Unrealized P/L
# --------------------------------------------------------------------
def compute_unrealized_pnl(
    portfolio_state: Optional[PortfolioState],
    current_price: float,
) -> Optional[float]:
    """
    Approximate unrealized P/L across open trades in the portfolio.

    Assumes:
      - Trade.size > 0 means long position.
      - No explicit shorts (or shorts use negative size).
    """
    if portfolio_state is None or not portfolio_state.open_trades:
        return 0.0

    price = float(current_price)
    total = 0.0

    for trade in portfolio_state.open_trades:
        entry_price = _to_float(trade.entry_price)
        size = _to_float(trade.size)
        if entry_price is None or size is None:
            continue

        # For now: long-only or signed size handles longs/shorts.
        pnl = (price - entry_price) * size
        total += pnl

    return total


# --------------------------------------------------------------------
# Last entry price & time since last trade
# --------------------------------------------------------------------
def compute_last_trade_info(
    portfolio_state: Optional[PortfolioState],
) -> Tuple[Optional[float], Optional[datetime], Optional[float]]:
    """
    Return:
      - last_entry_price
      - last_trade_opened_at (UTC)
      - seconds_since_last_trade
    """
    if portfolio_state is None or not portfolio_state.open_trades:
        return None, None, None

    # Use the most recently opened trade we know about
    latest = None
    for trade in portfolio_state.open_trades:
        if trade.opened_at is None:
            continue
        if latest is None or trade.opened_at > latest.opened_at:
            latest = trade

    if latest is None:
        return None, None, None

    last_entry_price = _to_float(latest.entry_price)
    opened_at = latest.opened_at

    if opened_at is not None:
        # normalize to aware UTC
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        else:
            opened_at = opened_at.astimezone(timezone.utc)

        now = datetime.now(timezone.utc)
        seconds_since = (now - opened_at).total_seconds()
    else:
        seconds_since = None

    return last_entry_price, opened_at, seconds_since


# --------------------------------------------------------------------
# Drawdown status (coarse, snapshot-based)
# --------------------------------------------------------------------
def compute_drawdown_status(
    portfolio_state: Optional[PortfolioState],
    unrealized_pnl: Optional[float] = None,
) -> dict:
    """
    Compute a coarse drawdown snapshot using the most recent DailySnapshot.

    Returns dict with:
      - current_equity
      - estimated_peak_equity
      - drawdown_abs
      - drawdown_pct
      - max_intraday_drawdown
    """
    if portfolio_state is None or portfolio_state.last_snapshot is None:
        return {
            "current_equity": None,
            "estimated_peak_equity": None,
            "drawdown_abs": None,
            "drawdown_pct": None,
            "max_intraday_drawdown": None,
        }

    snap = portfolio_state.last_snapshot

    ending_eq = _to_float(snap.ending_equity)
    snap_unrealized = _to_float(snap.unrealized_pnl)
    max_dd = _to_float(snap.max_intraday_drawdown)

    # Estimate current equity from last snapshot + unrealized P/L
    current_equity = None
    if ending_eq is not None:
        current_equity = ending_eq
        if unrealized_pnl is not None:
            current_equity += unrealized_pnl
        elif snap_unrealized is not None:
            current_equity += snap_unrealized

    # Very coarse peak estimation: peak ≈ current_equity - max_dd
    estimated_peak = None
    drawdown_abs = None
    drawdown_pct = None

    if current_equity is not None and max_dd is not None:
        estimated_peak = current_equity - max_dd
        drawdown_abs = max_dd
        if estimated_peak > 0:
            drawdown_pct = max_dd / estimated_peak

    return {
        "current_equity": current_equity,
        "estimated_peak_equity": estimated_peak,
        "drawdown_abs": drawdown_abs,
        "drawdown_pct": drawdown_pct,
        "max_intraday_drawdown": max_dd,
    }
