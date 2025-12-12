# import asyncio
# from datetime import datetime, timedelta, timezone

# from bot.core.event_loop_fix import apply_windows_event_loop_fix
# from bot.persistence.db import DB
# from bot.persistence.models import StrategyConfig
# from bot.backtesting.config import BacktestConfig
# from bot.backtesting.engine import run_backtest

# from bot.strategies.advanced.mean_reversion import MeanReversionStrategy


# ASSETS = [
#     ("BTC-USD", "BTC", "USD"),
#     ("ETH-USD", "ETH", "USD"),
#     ("XRP-USD", "XRP", "USD"),
#     ("DOGE-USD", "DOGE", "USD"),
#     ("LINK-USD", "LINK", "USD"),
# ]


# STRATEGY_PARAMS = {
#     "lookback": 12,
#     "z_entry": -1.4,
#     "z_exit": -0.25,

#     "stop_loss_pct": 0.3,
#     "take_profit_pct": 0.8,

#     "max_slippage_pct": 0.25,
#     "max_risk_pct": 0.02,
#     "max_daily_loss_pct": 0.03,
#     "max_trades_per_day": 15,
# }


# async def main():
#     print("\n==============================")
#     print("  MULTI-ASSET BACKTEST STARTING")
#     print("==============================\n")

#     db = DB()

#     # 3-month window (matches your imported history)
#     end_dt = datetime.now(timezone.utc)
#     start_dt = end_dt - timedelta(days=90)

#     results = []

#     for symbol, base, quote in ASSETS:
#         print(f"\n--- Running backtest for {symbol} ---\n")

#         # Ensure asset exists
#         asset = await db.get_or_create_asset(symbol, base, quote)

#         # Create a dedicated portfolio for this asset
#         portfolio = await db.add_portfolio(
#             name=f"Backtest - MR ({symbol})",
#             mode="backtest",
#             base_currency="USD",
#             starting_equity=500.0,
#         )

#         # Create StrategyConfig
#         async with db.get_session() as session:
#             cfg_row = StrategyConfig(
#                 name=f"mean_rev_{symbol.lower()}",
#                 description=f"Mean Reversion on {symbol}",
#                 params_json=STRATEGY_PARAMS,
#             )
#             session.add(cfg_row)
#             await session.commit()
#             await session.refresh(cfg_row)

#         # Build backtest config
#         cfg = BacktestConfig(
#             portfolio_id=portfolio.id,
#             asset_id=asset.id,
#             strategy_config_id=cfg_row.id,
#             strategy_class=MeanReversionStrategy,
#             strategy_params=STRATEGY_PARAMS,
#             timeframe="ONE_MINUTE",
#             start=start_dt,
#             end=end_dt,
#             fee_bps=1.0,
#             slippage_bps=0.0,
#             label=f"MR_{symbol}_3mo_1m",
#         )

#         # Run backtest
#         result = await run_backtest(db, cfg)

#         results.append(
#             (
#                 symbol,
#                 result.total_trades,
#                 result.win_rate,
#                 result.final_equity,
#             )
#         )

#     # ============================
#     # SUMMARY REPORT
#     # ============================
#     print("\n==============================")
#     print("   MULTI-ASSET SUMMARY")
#     print("==============================")

#     for symbol, trades, win_rate, equity in results:
#         print(
#             f"{symbol:8} | Trades: {trades:3d} "
#             f"| Win Rate: {win_rate*100:5.2f}% "
#             f"| Final Equity: {equity:8.2f}"
#         )

#     print("==============================\n")


# if __name__ == "__main__":
#     apply_windows_event_loop_fix()
#     asyncio.run(main())
import asyncio
from datetime import datetime, timedelta, timezone

from bot.core.event_loop_fix import apply_windows_event_loop_fix
from bot.persistence.db import DB
from bot.persistence.models import StrategyConfig

# OLD ENGINE REMOVED:
# from bot.backtesting.engine import run_backtest

# NEW FAST ENGINE:
from bot.backtesting.fast_engine import FastBacktestEngine   # ← UPDATED

from bot.strategies.advanced.mean_reversion import MeanReversionStrategy


ASSETS = [
    ("BTC-USD", "BTC", "USD"),
    ("ETH-USD", "ETH", "USD"),
    ("XRP-USD", "XRP", "USD"),
    ("DOGE-USD", "DOGE", "USD"),
    ("LINK-USD", "LINK", "USD"),
]


STRATEGY_PARAMS = {
    "lookback": 12,
    "z_entry": -1.4,
    "z_exit": -0.25,

    "stop_loss_pct": 0.3,
    "take_profit_pct": 0.8,

    "max_slippage_pct": 0.25,
    "max_risk_pct": 0.02,
    "max_daily_loss_pct": 0.03,
    "max_trades_per_day": 15,
}


async def main():
    print("\n==============================")
    print("  FAST MULTI-ASSET BACKTEST STARTING")
    print("==============================\n")

    db = DB()

    # 3 month window (from your imported history)
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=90)

    fast_engine = FastBacktestEngine(db)   # ← UPDATED

    results = []

    for symbol, base, quote in ASSETS:
        print(f"\n--- Running FAST backtest for {symbol} ---\n")

        # Ensure asset exists
        asset = await db.get_or_create_asset(symbol, base, quote)

        # Create a small $500 test portfolio
        portfolio = await db.add_portfolio(
            name=f"Fast Backtest - MR ({symbol})",
            mode="backtest",
            base_currency="USD",
            starting_equity=500.0,
        )

        # Create strategy config (kept for consistency)
        async with db.get_session() as session:
            cfg_row = StrategyConfig(
                name=f"mean_rev_{symbol.lower()}",
                description=f"Mean Reversion (FAST) on {symbol}",
                params_json=STRATEGY_PARAMS,
            )
            session.add(cfg_row)
            await session.commit()
            await session.refresh(cfg_row)

        # Instantiate strategy
        strategy = MeanReversionStrategy(STRATEGY_PARAMS)

        # RUN FAST ENGINE (replaces run_backtest)
        result = await fast_engine.run(      # ← UPDATED
            portfolio_equity=500.0,
            asset_id=asset.id,
            strategy=strategy,
            timeframe="ONE_MINUTE",
            start=start_dt,
            end=end_dt,
        )

        # Store summary
        results.append(
            (
                symbol,
                len(result.trades),
                result.win_rate,
                result.final_equity,
            )
        )

    # ============================
    # SUMMARY REPORT
    # ============================
    print("\n==============================")
    print("         FAST SUMMARY")
    print("==============================")

    for symbol, trades, win_rate, equity in results:
        print(
            f"{symbol:8} | Trades: {trades:4d} "
            f"| Win Rate: {win_rate*100:6.2f}% "
            f"| Final Equity: {equity:10.2f}"
        )

    print("==============================\n")


if __name__ == "__main__":
    apply_windows_event_loop_fix()
    asyncio.run(main())
