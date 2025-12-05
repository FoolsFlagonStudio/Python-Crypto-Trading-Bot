import asyncio
import selectors
import random
from datetime import datetime, timedelta, timezone

from bot.persistence.db import DB
from bot.strategies.green_candle import GreenCandleStrategy
from bot.strategies.runner import StrategyRunner
from bot.persistence.models import StrategyConfig


class TestCandle:
    """Simple candle object for testing."""

    def __init__(self, open_, close_, timestamp):
        self.open = open_
        self.close = close_
        self.timestamp = timestamp


async def main():
    db = DB()

    # Create strategy config in DB
    cfg = StrategyConfig(name="DummyConfig", params_json={})
    async with db.get_session() as session:
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    strategy_config_id = cfg.id

    # Ensure asset exists
    asset = await db.get_or_create_asset("BTC-USD", "BTC", "USD")

    # Create portfolio
    portfolio = await db.add_portfolio("Strategy Test Portfolio", "backtest", "USD")

    # Create runner
    strategy = GreenCandleStrategy()
    runner = StrategyRunner(
        strategy=strategy,
        db=db,
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        strategy_config_id=strategy_config_id,
    )

    # Simulated candles (alternating green/red)
    now = datetime.now(timezone.utc)
    candles = []

    for i in range(10):
        if i % 2 == 0:
            # green
            candles.append(TestCandle(100, 105, now - timedelta(minutes=i)))
        else:
            # red
            candles.append(TestCandle(105, 100, now - timedelta(minutes=i)))

    results = await runner.run(candles)
    for r in results:
        print(r)


if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
