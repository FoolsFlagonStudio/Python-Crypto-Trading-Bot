import os
import time
import asyncio
from typing import List, Dict, Any
from coinbase.rest import RESTClient


class CoinbaseClient:
    """
    Thin wrapper around coinbase-advanced-py RESTClient just for fetching candles
    in a bot-friendly way.

    IMPORTANT:
    Coinbase Advanced requires UNIX timestamps (in seconds) as *strings* for
    start / end parameters on get_candles().
    """

    def __init__(self):
        self.client = RESTClient(
            api_key=os.getenv("COINBASE_API_KEY"),
            api_secret=os.getenv("COINBASE_API_SECRET"),
        )

    # ---------------------------------------------------------------
    # Helper to call sync RESTClient inside async world
    # ---------------------------------------------------------------
    async def _run_sync(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: fn(*args, **kwargs)
        )

    # ---------------------------------------------------------------
    # Fetch candles (async wrapper)
    # ---------------------------------------------------------------
    async def fetch_candles(
        self,
        product_id: str,
        start: int,
        end: int,
        granularity: str = "ONE_MINUTE",
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical candles by UNIX timestamps.

        Coinbase expects:
            product_id = "BTC-USD"
            start = "UNIX timestamp as string"
            end   = "UNIX timestamp as string"
            granularity ∈ { "ONE_MINUTE", "FIVE_MINUTE", "FIFTEEN_MINUTE",
                            "ONE_HOUR", "ONE_DAY" }
        """

        # Convert ints to strings — REQUIRED by Coinbase API
        start_s = str(start)
        end_s = str(end)

        response = await self._run_sync(
            self.client.get_candles,
            product_id=product_id,
            start=start_s,
            end=end_s,
            granularity=granularity,
        )

        candles = response.candles or []

        # Normalize to bot-friendly dicts
        normalized = [
            {
                "start": c.start,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
            }
            for c in candles
        ]

        return normalized

    # ---------------------------------------------------------------
    # Convenience helper for easy usage:
    # Fetch last N minutes of candles
    # ---------------------------------------------------------------
    async def fetch_last_minutes(
        self, product_id: str, minutes: int, granularity="ONE_MINUTE"
    ):
        now = int(time.time())
        start = now - (minutes * 60)
        return await self.fetch_candles(product_id, start, now, granularity)
