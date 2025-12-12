# scripts/data/load_history.py

import asyncio
from bot.persistence.db import DB
from bot.data.historical_loader import HistoricalLoader


async def main():
    db = DB()
    loader = HistoricalLoader(db)

    n = await loader.load(
        product_id="BTC-USD",
        granularity="ONE_MINUTE",
        days=90,
        commit_batch=500,
        reset_existing=True,  
    )

    print(f"Inserted {n} candles.")

if __name__ == "__main__":
    asyncio.run(main())
