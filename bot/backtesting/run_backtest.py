# bot/backtesting/run_backtest.py

import asyncio
from datetime import datetime, timedelta, timezone

from bot.core.event_loop_fix import apply_windows_event_loop_fix
from bot.persistence.db import DB
from bot.persistence.models import StrategyConfig
from bot.backtesting.config import BacktestConfig
from bot.backtesting.engine import run_backtest

# Strategy to test
from bot.strategies.advanced.mean_reversion import MeanReversionStrategy


async def main():
    print("\n==============================")
    print(" BACKTEST RUN STARTING")
    print("==============================\n")

    db = DB()

    # ---------------------------------------------------------
    # 1) Ensure asset exists for BTC-USD
    # ---------------------------------------------------------
    asset = await db.get_or_create_asset("BTC-USD", "BTC", "USD")

    # ---------------------------------------------------------
    # 2) Create a dedicated backtest portfolio
    #    (you can reuse it by persisting the ID if you want)
    # ---------------------------------------------------------
    portfolio = await db.add_portfolio(
        name="Backtest - Mean Reversion (BTC-USD)",
        mode="backtest",
        base_currency="USD",
        starting_equity=10_000.0,
    )

    # ---------------------------------------------------------
    # 3) Create a StrategyConfig row
    # ---------------------------------------------------------
    strategy_params = {
        "lookback": 20,
        "threshold_pct": 0.01,   # 1% deviation
        "use_volatility": False,
        "vol_window": 20,
        "vol_mult": 1.0,

        # execution / risk params used elsewhere:
        "max_slippage_pct": 0.25,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
        "max_risk_pct": 0.02,
        "max_daily_loss_pct": 0.03,
        "max_trades_per_day": 6,
    }

    async with db.get_session() as session:
        cfg_row = StrategyConfig(
            name="mean_reversion_btcusd_backtest",
            description="Mean Reversion on BTC-USD with 1m candles",
            params_json=strategy_params,
        )
        session.add(cfg_row)
        await session.commit()
        await session.refresh(cfg_row)

    # ---------------------------------------------------------
    # 4) Define the time window for backtest
    #    Match the loader: last 3 days of ONE_MINUTE candles
    # ---------------------------------------------------------
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=3)

    # ---------------------------------------------------------
    # 5) Build BacktestConfig
    # ---------------------------------------------------------
    cfg = BacktestConfig(
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        strategy_config_id=cfg_row.id,
        strategy_class=MeanReversionStrategy,
        strategy_params=strategy_params,
        timeframe="ONE_MINUTE",   # must match what you stored in candles.timeframe
        start=start_dt,
        end=end_dt,
        fee_bps=1.0,
        slippage_bps=0.0,
        label="MR_BTCUSD_3d_1m",
        notes="Mean reversion test on 3 days of BTC-USD 1m data",
    )

    # ---------------------------------------------------------
    # 6) Run the backtest
    # ---------------------------------------------------------
    result = await run_backtest(db, cfg)

    # ---------------------------------------------------------
    # 7) Print result summary
    # ---------------------------------------------------------
    print("\n==============================")
    print(" BACKTEST RESULT")
    print("==============================")
    print(f"BacktestRun ID : {result.backtest_run_id}")
    print(f"Start Equity   : {result.start_equity:.2f}")
    print(f"Final Equity   : {result.final_equity:.2f}")
    print(f"Total Trades   : {result.total_trades}")
    print(f"Win Rate       : {result.win_rate*100:.2f}%")
    print(f"Max Drawdown   : {result.max_drawdown*100:.2f}% (placeholder)")
    print(f"Signals Seen   : {result.signals_count}")
    print("==============================\n")


if __name__ == "__main__":
    apply_windows_event_loop_fix()
    asyncio.run(main())
