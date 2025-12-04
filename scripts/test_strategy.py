import argparse
import asyncio
import logging
from datetime import datetime

from bot.persistence.db import DB
from bot.persistence.models import StrategyConfig
from bot.strategies.runner import StrategyRunner

# Strategies
from bot.strategies.green_candle import GreenCandleStrategy
from bot.strategies.advanced.moving_average_crossover import MovingAverageCrossoverStrategy
from bot.strategies.advanced.rsi_strategy import RSIStrategy
from bot.strategies.advanced.breakout import BreakoutStrategy
from bot.strategies.advanced.support_resistance_strategy import SupportResistanceStrategy
from bot.strategies.advanced.mean_reversion import MeanReversionStrategy
from bot.strategies.advanced.trend_following import TrendFollowingStrategy

# Scenario generators (you created scripts/simulated_markets.py earlier)
from scripts.simulated_markets import SCENARIOS

# ---------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------

STRATEGY_MAP = {
    "green": GreenCandleStrategy,
    "ma": MovingAverageCrossoverStrategy,
    "rsi": RSIStrategy,
    "breakout": BreakoutStrategy,
    "sr": SupportResistanceStrategy,
    "mean": MeanReversionStrategy,
    "trend": TrendFollowingStrategy,
}

# ---------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------


async def run_strategy(strategy_key: str, scenario_key: str, n_candles: int):
    if strategy_key not in STRATEGY_MAP:
        raise ValueError(
            f"Unknown strategy '{strategy_key}'. "
            f"Available: {', '.join(STRATEGY_MAP.keys())}"
        )

    if scenario_key not in SCENARIOS:
        raise ValueError(
            f"Unknown scenario '{scenario_key}'. "
            f"Available: {', '.join(SCENARIOS.keys())}"
        )

    StrategyClass = STRATEGY_MAP[strategy_key]
    scenario_fn = SCENARIOS[scenario_key]

    print(f"\n▶ Initializing DB and strategy: {strategy_key}")

    db = DB()

    # ---------------------------------------------------------------
    # Strategy config row
    # ---------------------------------------------------------------
    cfg = StrategyConfig(name=f"{strategy_key}_config", params_json={})
    async with db.get_session() as session:
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    strategy_config_id = cfg.id

    # ---------------------------------------------------------------
    # Asset + portfolio
    # ---------------------------------------------------------------
    asset = await db.get_or_create_asset("BTC-USD", "BTC", "USD")

    portfolio = await db.add_portfolio(
        name=f"Test Portfolio - {strategy_key}",
        mode="backtest",
        base_currency="USD",
    )

    # ---------------------------------------------------------------
    # Instantiate strategy + runner
    # ---------------------------------------------------------------
    strategy = StrategyClass()

    runner = StrategyRunner(
        strategy=strategy,
        db=db,
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        strategy_config_id=strategy_config_id,
    )

    # ---------------------------------------------------------------
    # Generate candles from chosen scenario
    # ---------------------------------------------------------------
    print(
        f"\n▶ Generating {n_candles} candles "
        f"using scenario: '{scenario_key}' ..."
    )
    candles = scenario_fn(n=n_candles)
    print(f"▶ Generated {len(candles)} synthetic candles.\n")

    # ---------------------------------------------------------------
    # Run strategy
    # ---------------------------------------------------------------
    print(f"▶ Running strategy '{strategy_key}'...\n")

    signals = await runner.run(candles)

    # ---------------------------------------------------------------
    # Print results
    # ---------------------------------------------------------------
    print("\n=== SIGNALS GENERATED ===\n")
    if not signals:
        print("(no signals generated)")
    else:
        for sig in signals:
            ts = sig.timestamp
            if isinstance(ts, datetime):
                ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts_str = str(ts)

            reason = None
            if sig.metadata:
                reason = sig.metadata.get("reason")

            print(
                f"{ts_str} | {sig.signal_type.upper()} "
                f"| price={sig.price} | reason={reason}"
            )

    print("\n--- Done ---\n")
    return signals


# ---------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Strategy + market-scenario test harness"
    )

    parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        help="Strategy key: green, ma, rsi, breakout, sr, mean, trend",
    )

    parser.add_argument(
        "--scenario",
        type=str,
        default="random",
        help=(
            "Market scenario: uptrend, downtrend, range, "
            "breakout_up, breakout_down, sr, high_vol, random"
        ),
    )

    parser.add_argument(
        "--candles",
        type=int,
        default=120,
        help="Number of candles to generate for the scenario",
    )

    args = parser.parse_args()

    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(
        run_strategy(args.strategy, args.scenario, args.candles)
    )


if __name__ == "__main__":
    main()
