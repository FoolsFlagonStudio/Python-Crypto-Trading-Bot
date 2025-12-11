import asyncio
from bot.persistence.db import DB
from bot.data.historical_loader import HistoricalLoader


async def main():
    db = DB()
    loader = HistoricalLoader(db)

    n = await loader.load(
        product_id="BTC-USD",
        granularity="ONE_MINUTE",
        days=3,          # last 72 hours
        commit_batch=500
    )

    print(f"Inserted {n} candles.")


if __name__ == "__main__":
    asyncio.run(main())
