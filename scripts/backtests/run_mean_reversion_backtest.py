# scripts/backtests/run_mean_reversion_backtest.py

import asyncio
from datetime import datetime, timezone

from bot.core.event_loop_fix import apply_windows_event_loop_fix
from bot.persistence.db import DB
from bot.execution.simulated import SimulatedExecutionEngine
from bot.backtesting.engine import BacktestEngine
from bot.strategies.advanced.mean_reversion import MeanReversionStrategy


def _make_engine():
    """
    Factory for the simulated execution engine.

    Adjust params here to tune fee/slippage behavior for backtests.
    """
    # If your SimulatedExecutionEngine takes params, wire them here.
    # Example (adjust to your real signature):
    # return SimulatedExecutionEngine(fee_bps=10, slippage_bps=5)
    return SimulatedExecutionEngine()


async def main():
    apply_windows_event_loop_fix()

    db = DB()
    bt_engine = BacktestEngine(db=db, execution_engine_factory=_make_engine)

    # IDs should exist in your DB and be dedicated to this backtest.
    PORTFOLIO_ID = 2        # e.g. "mean_revert_backtest"
    ASSET_ID = 1            # whatever asset row you created (e.g. BTC-USD)
    STRATEGY_CONFIG_ID = 1  # optional linkage, or create a dedicated config

    TIMEFRAME = "1h"
    START = datetime(2024, 1, 1, tzinfo=timezone.utc)
    END = datetime(2024, 3, 1, tzinfo=timezone.utc)

    # Strategy params (tune as desired)
    params = {
        "lookback": 20,
        "threshold_pct": 0.01,
        "use_volatility": True,
        "vol_window": 20,
        "vol_mult": 1.0,
        "max_history": 200,
        # Risk-related params (hook into RiskManager)
        "max_risk_pct": 0.02,
        "max_daily_loss_pct": 0.03,
        "max_trades_per_day": 6,
        # Slippage controls for OrderManager
        "max_slippage_pct": 0.25,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
    }

    # 1) Load candles from DB (previously ingested from Coinbase etc.)
    candles = await bt_engine.load_candles_from_db(
        asset_id=ASSET_ID,
        timeframe=TIMEFRAME,
        start=START,
        end=END,
    )
    if not candles:
        print("No candles found for given range/timeframe. Seed some data first.")
        return

    # 2) Run the backtest
    result = await bt_engine.run_backtest(
        portfolio_id=PORTFOLIO_ID,
        asset_id=ASSET_ID,
        strategy_config_id=STRATEGY_CONFIG_ID,
        strategy_class=MeanReversionStrategy,
        strategy_params=params,
        candles=candles,
        label="MeanReversion 1h BTCUSD (2024-01 → 2024-03)",
        data_source="candles_db.coinbase_1h",
        reset_portfolio_state=True,  # wipe previous backtest data
    )

    # 3) Print summary
    print("\n=== BACKTEST SUMMARY ===")
    print(f"Run ID:         {result.run_id}")
    print(f"Dates:          {result.start_date} → {result.end_date}")
    print(
        f"Equity:         {result.initial_equity:.2f} → {result.final_equity:.2f}")
    print(f"Realized PnL:   {result.realized_pnl:.2f}")
    print(f"Total trades:   {result.total_trades}")
    print(f"Wins / Losses:  {result.winning_trades} / {result.losing_trades}")
    print(f"Win rate:       {result.win_rate * 100:.1f}%")
    print("========================\n")


if __name__ == "__main__":
    asyncio.run(main())
