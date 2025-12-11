import asyncio
from bot.data.coinbase_client import CoinbaseClient


async def main():
    coin = CoinbaseClient()
    candles = await coin.fetch_last_minutes("BTC-USD", minutes=60)

    print(f"Fetched {len(candles)} candles")
    for c in candles[:5]:
        print(c)

if __name__ == "__main__":
    asyncio.run(main())
