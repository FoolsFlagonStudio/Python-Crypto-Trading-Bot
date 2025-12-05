import asyncio
import selectors
from bot.persistence.db import DB


async def main():
    db = DB()

    print("Adding asset...")
    asset = await db.add_asset("BTC-USD", "BTC", "USD")
    print("Added:", asset)

    print("Querying asset...")
    result = await db.get_asset_by_symbol("BTC-USD")
    print("Found:", result)

    print("Adding portfolio...")
    pf = await db.add_portfolio("Test Portfolio", "backtest", "USD")
    print("Added:", pf)


if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
