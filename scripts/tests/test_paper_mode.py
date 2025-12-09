import asyncio
from datetime import datetime, timezone

from bot.runner_factory import build_runner
from bot.strategies.signals import StrategySignal, SignalType
from bot.persistence.db import DB
from bot.persistence.models import Portfolio, Asset, StrategyConfig


# A tiny fake candle object for testing
class FakeCandle:
    def __init__(self, close: float):
        self.close = close
        self.high = close * 1.002
        self.low = close * 0.998
        self.timestamp = datetime.now(timezone.utc)


async def run_test():
    print("\n==============================")
    print(" PAPER MODE TEST STARTING")
    print("==============================\n")

    db = DB()

    # --------------------------------------------------
    # Strategy params for the test
    # --------------------------------------------------
    params = {
        "max_slippage_pct": 0.25,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
    }

    # --------------------------------------------------
    # Seed minimal DB state for the test
    # --------------------------------------------------

    # 1) Create a paper portfolio
    portfolio = await db.add_portfolio(
        name="Paper Mode Test PF",
        mode="paper",
        base_currency="USD",
        starting_equity=10_000.0,
    )

    # 2) Ensure we have an asset (BTC-USD)
    asset = await db.get_or_create_asset(
        symbol="BTC-USD",
        base="BTC",
        quote="USD",
    )

    # 3) Create a simple StrategyConfig
    async with db.get_session() as session:
        strategy_config = StrategyConfig(
            name="Dummy Strategy Config",
            description="Paper mode test strategy",
            params_json=params,
        )
        session.add(strategy_config)
        await session.commit()
        await session.refresh(strategy_config)

        PORTFOLIO_ID = portfolio.id
        ASSET_ID = asset.id
        STRATEGY_CONFIG_ID = strategy_config.id

    # --------------------------------------------------
    # Dummy strategy: first candle ENTER, second EXIT
    # --------------------------------------------------
    class DummyStrategy:
        def __init__(self, params: dict):
            self.params = params

        def generate_signal(self, candle, state):
            # If we already have open trades, issue EXIT
            if state.open_trades:
                return StrategySignal(
                    timestamp=datetime.now(timezone.utc),
                    signal_type=SignalType.EXIT,
                    price=candle.close,
                    metadata={"reason": "dummy_exit"},
                )
            # Otherwise, first call → ENTER
            return StrategySignal(
                timestamp=datetime.now(timezone.utc),
                signal_type=SignalType.ENTER,
                price=candle.close,
                metadata={"reason": "dummy_enter"},
            )

    # --------------------------------------------------
    # Build the runner (PAPER mode chosen via .env config)
    # --------------------------------------------------
    runner = await build_runner(
        portfolio_id=PORTFOLIO_ID,
        asset_id=ASSET_ID,
        strategy_config_id=STRATEGY_CONFIG_ID,
        strategy_params=params,
        strategy_class=DummyStrategy,
    )

    # Two fake candles: one to enter, one to exit
    candles = [
        FakeCandle(100.0),  # ENTER at 100
        FakeCandle(102.0),  # EXIT at 102
    ]

    print("Running strategy runner in PAPER mode...\n")
    signals = await runner.run(candles)

    print("\nSignals produced:")
    for s in signals:
        print(f"  - {s.signal_type} @ {s.price}")

    print("\nPaper mode test complete.")
    print("==============================\n")


if __name__ == "__main__":
    asyncio.run(run_test())
