import asyncio
from datetime import datetime, timezone
import os

from bot.persistence.db import DB
from bot.data.coinbase_client import CoinbaseMarketData
from bot.data.candle_normalizer import normalize_coinbase_candles


async def main():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")

    if not api_key or not api_secret:
        raise RuntimeError("Missing Coinbase API credentials.")

    db = DB()
    coin = CoinbaseMarketData(api_key, api_secret)

    # CHOOSE YOUR ASSET
    symbol = "BTC-USD"

    # Lookup/create asset row
    asset = await db.get_or_create_asset(
        symbol=symbol, base="BTC", quote="USD"
    )

    # RANGE TO IMPORT
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end   = datetime(2024, 3, 1, tzinfo=timezone.utc)

    raw = await coin.fetch_candles(
        symbol=symbol,
        start=start,
        end=end,
        granularity="ONE_HOUR",
    )

    print(f"Fetched {len(raw)} candles from Coinbase.")

    rows = normalize_coinbase_candles(
        raw=raw,
        asset_id=asset.id,
        timeframe="1h",
        source="coinbase",
    )

    await db.upsert_candles(rows)

    print(f"Inserted/Updated {len(rows)} rows into DB.")


if __name__ == "__main__":
    asyncio.run(main())
