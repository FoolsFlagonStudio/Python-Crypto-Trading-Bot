# bot/backtesting/fast_engine.py

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select

from bot.persistence.db import DB
from bot.persistence.models import Candle
from bot.core.logger import get_logger
from bot.strategies.signals import StrategySignal

logger = get_logger(__name__)


# ============================================================
# Data Classes
# ============================================================

@dataclass
class FastTrade:
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    pnl: Optional[float]
    size: float  # FRACTIONAL size (risk-based)


@dataclass
class FastBacktestResult:
    start_equity: float
    final_equity: float
    trades: List[FastTrade]
    win_rate: float
    max_drawdown: float
    signals: int


# ============================================================
# Fast Backtesting Engine
# ============================================================

class FastBacktestEngine:
    """
    Extremely fast in-memory backtest loop.

    Differences from real engine:
    ✔ No DB writes
    ✔ No OrderManager
    ✔ No execution engine
    ✔ No slippage simulation (optional to add later)

    But:
    ✔ Strategy.on_bar() logic is identical
    ✔ Risk is applied properly
    ✔ Position sizes follow max_risk_pct rule
    ✔ stop_loss / take_profit enforced
    """

    def __init__(self, db: DB):
        self.db = db

    # ------------------------------------------------------------
    async def run(
        self,
        *,
        portfolio_equity: float,
        asset_id: int,
        strategy,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> FastBacktestResult:

        # --------------------------------------------------------
        # 1) Load candles ONCE
        # --------------------------------------------------------
        async with self.db.get_session() as session:
            result = await session.execute(
                select(Candle)
                .where(Candle.asset_id == asset_id)
                .where(Candle.timeframe == timeframe)
                .where(Candle.timestamp >= start)
                .where(Candle.timestamp <= end)
                .order_by(Candle.timestamp.asc())
            )
            candles = list(result.scalars().all())

        if not candles:
            raise RuntimeError("No candles available for fast backtest.")

        logger.info(f"[FAST BT] Loaded {len(candles)} candles")

        # --------------------------------------------------------
        # 2) In-memory state
        # --------------------------------------------------------
        equity = portfolio_equity
        peak_equity = equity
        trades: List[FastTrade] = []
        open_trade: Optional[FastTrade] = None

        signals_seen = 0

        # Reset strategy internal buffers
        if hasattr(strategy, "reset"):
            strategy.reset()

        # Pull risk params
        params = strategy.params
        max_risk_pct = float(params.get("max_risk_pct", 0.02))
        stop_loss_pct = float(params.get("stop_loss_pct", 0.0)) / 100
        take_profit_pct = float(params.get("take_profit_pct", 0.0)) / 100

        # --------------------------------------------------------
        # 3) Candle-by-candle loop
        # --------------------------------------------------------
        for c in candles:

            # ====================================================
            # AUTO EXIT CHECK (SL / TP)
            # ====================================================
            if open_trade is not None:
                entry = open_trade.entry_price
                size = open_trade.size
                price = float(c.close)

                # STOP LOSS
                if stop_loss_pct > 0 and price <= entry * (1 - stop_loss_pct):
                    risk_pct = strategy.params.get("max_risk_pct", 0.02)
                    position_size = (equity * risk_pct) / open_trade.entry_price

                    pnl = position_size * (price - open_trade.entry_price)
                    equity += pnl

                    trades.append(
                        FastTrade(
                            entry_time=open_trade.entry_time,
                            exit_time=c.timestamp,
                            entry_price=entry,
                            exit_price=price,
                            pnl=pnl,
                            size=size,
                        )
                    )
                    open_trade = None
                    peak_equity = max(peak_equity, equity)
                    continue

                # TAKE PROFIT
                if take_profit_pct > 0 and price >= entry * (1 + take_profit_pct):
                    pnl = (price - entry) * size
                    equity += pnl
                    trades.append(
                        FastTrade(
                            entry_time=open_trade.entry_time,
                            exit_time=c.timestamp,
                            entry_price=entry,
                            exit_price=price,
                            pnl=pnl,
                            size=size,
                        )
                    )
                    open_trade = None
                    peak_equity = max(peak_equity, equity)
                    continue

            # ====================================================
            # STRATEGY SIGNAL GENERATION
            # ====================================================
            sig: StrategySignal | None = strategy.on_bar(candle=c)
            if sig is None:
                continue

            signals_seen += 1
            stype = sig.signal_type.lower()
            price = sig.price

            # ====================================================
            # ENTRY
            # ====================================================
            if stype == "enter" and open_trade is None:
                # Risk-based sizing
                risk_amount = equity * max_risk_pct
                size = risk_amount / price

                open_trade = FastTrade(
                    entry_time=c.timestamp,
                    exit_time=None,
                    entry_price=price,
                    exit_price=None,
                    pnl=None,
                    size=size,
                )
                continue

            # ====================================================
            # EXIT
            # ====================================================
            if stype == "exit" and open_trade is not None:

                entry = open_trade.entry_price
                size = open_trade.size

                pnl = (price - entry) * size
                equity += pnl

                open_trade.exit_price = price
                open_trade.exit_time = c.timestamp
                open_trade.pnl = pnl

                trades.append(open_trade)
                open_trade = None

                peak_equity = max(peak_equity, equity)
                continue

        # --------------------------------------------------------
        # 4) Compute metrics
        # --------------------------------------------------------
        wins = [t for t in trades if t.pnl and t.pnl > 0]
        win_rate = len(wins) / len(trades) if trades else 0

        max_drawdown = (
            (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        )

        return FastBacktestResult(
            start_equity=portfolio_equity,
            final_equity=equity,
            trades=trades,
            win_rate=win_rate,
            max_drawdown=max_drawdown,
            signals=signals_seen,
        )
