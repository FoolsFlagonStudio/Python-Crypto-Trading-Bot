import asyncio
from bot.persistence.db import DB
from bot.data.historical_loader import HistoricalLoader

ASSETS = [
    "BTC-USD",
    "ETH-USD",
    "XRP-USD",
    "DOGE-USD",
    "LINK-USD",
]


async def main():
    db = DB()
    loader = HistoricalLoader(db)

    for asset in ASSETS:
        print(f"\n=== Fetching 6 months for {asset} ===")
        n = await loader.load(
            product_id=asset,
            granularity="FIFTEEN_MINUTE",
            days=90,
            reset_existing=True,
            commit_batch=500,
        )
        print(f"Inserted {n} candles.")

if __name__ == "__main__":
    asyncio.run(main())
