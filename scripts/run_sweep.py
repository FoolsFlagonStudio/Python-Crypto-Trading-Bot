# scripts/backtests/run_sweep.py

import asyncio
import importlib
import itertools
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot.core.event_loop_fix import apply_windows_event_loop_fix
from bot.persistence.db import DB
from bot.execution.simulated import SimulatedExecutionEngine
from bot.backtesting.engine import BacktestEngine


def _make_engine():
    # Adjust if your simulated engine takes args
    return SimulatedExecutionEngine()


def _import_strategy(path: str):
    """
    Import a Strategy class given a dotted path like:
      "bot.strategies.advanced.mean_reversion.MeanReversionStrategy"
    """
    module_name, cls_name = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, cls_name)


def _parse_iso_dt(s: str) -> datetime:
    # basic ISO with 'Z'
    if s.endswith("Z"):
        s = s[:-1]
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(s)


async def main(config_path: str):
    apply_windows_event_loop_fix()

    cfg = json.loads(Path(config_path).read_text())

    portfolio_id = cfg["portfolio_id"]
    asset_id = cfg["asset_id"]
    strategy_config_id = cfg["strategy_config_id"]
    timeframe = cfg["timeframe"]
    start = _parse_iso_dt(cfg["start"])
    end = _parse_iso_dt(cfg["end"])

    strategy_cls = _import_strategy(cfg["strategy_path"])
    base_params = cfg.get("base_params", {})
    sweep = cfg.get("sweep", {})

    # Build param grid
    keys = list(sweep.keys())
    values_product = itertools.product(*(sweep[k] for k in keys))

    db = DB()
    bt_engine = BacktestEngine(db=db, execution_engine_factory=_make_engine)

    # Pre-load candles once so all runs share identical data
    candles = await bt_engine.load_candles_from_db(
        asset_id=asset_id,
        timeframe=timeframe,
        start=start,
        end=end,
    )
    if not candles:
        print("No candles found for config; aborting.")
        return

    results: list[dict[str, Any]] = []

    for combo in values_product:
        override = dict(zip(keys, combo))
        params = {**base_params, **override}

        label = f"MeanRevert sweep {override}"
        print(f"\n=== Running backtest {label} ===")

        result = await bt_engine.run_backtest(
            portfolio_id=portfolio_id,
            asset_id=asset_id,
            strategy_config_id=strategy_config_id,
            strategy_class=strategy_cls,
            strategy_params=params,
            candles=candles,
            label=label,
            data_source=f"sweep:{timeframe}",
            reset_portfolio_state=True,
        )

        row = {
            **override,
            "run_id": result.run_id,
            "initial_equity": result.initial_equity,
            "final_equity": result.final_equity,
            "realized_pnl": result.realized_pnl,
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
        }
        results.append(row)

    # Basic text summary (later we’ll export CSV / Jupyter)
    print("\n=== SWEEP SUMMARY ===")
    for r in results:
        print(
            f"{r} | pnl={r['realized_pnl']:.2f} "
            f"trades={r['total_trades']} win_rate={r['win_rate']*100:.1f}%"
        )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: poetry run python scripts/backtests/run_sweep.py configs/backtests/mean_reversion_sweep.json")
    else:
        asyncio.run(main(sys.argv[1]))
