# scripts/backtests/sweep_strategies.py

import asyncio
from datetime import datetime, timedelta, timezone
from itertools import product

from bot.persistence.db import DB
from bot.backtesting.fast_engine import FastBacktestEngine
from bot.persistence.models import Candle
# Import strategies
from bot.strategies.advanced.mean_reversion import MeanReversionStrategy
from bot.strategies.advanced.trend_following import TrendFollowingStrategy
from bot.strategies.advanced.breakout import BreakoutStrategy
from bot.strategies.advanced.moving_average_crossover import MovingAverageCrossoverStrategy
from bot.strategies.advanced.rsi_strategy import RSIStrategy
from bot.strategies.advanced.support_resistance_strategy import SupportResistanceStrategy
from sqlalchemy import select


# ---------------------------------------------------------
# Assets to test
# ---------------------------------------------------------
ASSETS = [
    ("BTC-USD", "BTC", "USD"),
    ("ETH-USD", "ETH", "USD"),
    ("XRP-USD", "XRP", "USD"),
    ("DOGE-USD", "DOGE", "USD"),
    ("LINK-USD", "LINK", "USD"),
]

TIMEFRAME = "FIFTEEN_MINUTE"  # later 15m
END = datetime.now(timezone.utc)
START = END - timedelta(days=90)
STARTING_EQUITY = 500.0


# ---------------------------------------------------------
# Parameter grids per strategy
# ---------------------------------------------------------

MEAN_REVERSION_GRID = [
    {"lookback": lb, "z_entry": ze, "z_exit": zx,
     "stop_loss_pct": 0.3, "take_profit_pct": 0.8}
    for lb, ze, zx in product(
        [8, 12, 16],
        [-1.0, -1.4],
        [-0.1, -0.25],
    )
]

TREND_FOLLOWING_GRID = [
    {"ema_period": ep, "confirm_period": cp}
    for ep, cp in product(
        [20, 50],
        [2, 3]
    )
]

BREAKOUT_GRID = [
    {"lookback": lb, "atr_mult": am}
    for lb, am in product(
        [20, 40],
        [1.0, 2.0]
    )
]

MA_CROSSOVER_GRID = [
    {"fast_window": f, "slow_window": s}
    for f, s in product(
        [8, 12],
        [20, 30]
    )
]

RSI_GRID = [
    {"period": p, "lower": l, "upper": u}
    for p, l, u in product(
        [14, 21],
        [25, 30],
        [70, 75],
    )
]

SUPPORT_RES_GRID = [
    {"left": l, "right": r, "tolerance_pct": t}
    for l, r, t in product(
        [2, 3],
        [2, 3],
        [0.003, 0.006]
    )
]

STRATEGY_CONFIGS = {
    "mean_reversion": (MeanReversionStrategy, MEAN_REVERSION_GRID),
    "trend_following": (TrendFollowingStrategy, TREND_FOLLOWING_GRID),
    "breakout": (BreakoutStrategy, BREAKOUT_GRID),
    "ma_crossover": (MovingAverageCrossoverStrategy, MA_CROSSOVER_GRID),
    "rsi": (RSIStrategy, RSI_GRID),
    "support_resistance": (SupportResistanceStrategy, SUPPORT_RES_GRID),
}


# ---------------------------------------------------------
# Main sweeping engine
# ---------------------------------------------------------

async def main():
    print("\n=======================================")
    print("     MULTI-STRATEGY PARAM SWEEP")
    print("=======================================\n")

    db = DB()
    fast_bt = FastBacktestEngine(db)

    results = []

    for symbol, base, quote in ASSETS:
        print(f"\n----------------------------")
        print(f"Asset: {symbol}")
        print(f"----------------------------")

        asset = await db.get_or_create_asset(symbol, base, quote)

        # Load candles once per asset
        candles = await fast_bt.db.load_candles(
            asset_id=asset.id,
            timeframe=TIMEFRAME,
            start=START,
            end=END,
        ) if hasattr(fast_bt.db, "load_candles") else None

        # fallback using SQLAlchemy (same as fast_engine)
        if candles is None:
            async with db.get_session() as session:
                candles = (
                    await session.execute(
                        select(Candle)
                        .where(Candle.asset_id == asset.id)
                        .where(Candle.timeframe == TIMEFRAME)
                        .where(Candle.timestamp >= START)
                        .where(Candle.timestamp <= END)
                        .order_by(Candle.timestamp.asc())
                    )
                ).scalars().all()

        print(f"Loaded {len(candles)} candles")

        # Sweep each strategy
        for strat_name, (StrategyClass, grid) in STRATEGY_CONFIGS.items():
            print(f"  Testing Strategy: {strat_name} ({len(grid)} configs)")

            for params in grid:
                strat = StrategyClass(params)

                bt_result = await fast_bt.run(
                    portfolio_equity=STARTING_EQUITY,
                    asset_id=asset.id,
                    strategy=strat,
                    timeframe=TIMEFRAME,
                    start=START,
                    end=END,
                )

                results.append({
                    "asset": symbol,
                    "strategy": strat_name,
                    "params": params,
                    "final_equity": bt_result.final_equity,
                    "win_rate": bt_result.win_rate,
                    "trades": len(bt_result.trades),
                    "max_drawdown": bt_result.max_drawdown,
                })

    # ---------------------------------------------------------
    # OUTPUT SUMMARY
    # ---------------------------------------------------------
    print("\n=======================================")
    print("             TOP RESULTS")
    print("=======================================\n")

    # Top results for each asset/strategy
    for asset in [a[0] for a in ASSETS]:
        print(f"\n===== {asset} =====")
        for strat_name in STRATEGY_CONFIGS.keys():
            subset = [r for r in results if r["asset"]
                      == asset and r["strategy"] == strat_name]
            if not subset:
                continue

            top = sorted(
                subset, key=lambda x: x["final_equity"], reverse=True)[:3]

            print(f"\n  Strategy: {strat_name}")
            for t in top:
                print(
                    f"    Equity={t['final_equity']:.2f} | Win={t['win_rate']*100:.1f}% | Trades={t['trades']} | Params={t['params']}")


if __name__ == "__main__":
    asyncio.run(main())
