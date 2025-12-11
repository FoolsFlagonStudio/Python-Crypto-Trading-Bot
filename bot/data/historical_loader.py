# bot/data/historical_loader.py

from __future__ import annotations
import datetime
import time
from typing import List, Optional

from bot.data.coinbase_client import CoinbaseClient
from bot.persistence.db import DB
from bot.persistence.models import Candle
from bot.core.logger import get_logger
from sqlalchemy import insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = get_logger(__name__)


class HistoricalLoader:
    """
    Loads historical candles from Coinbase Advanced API and stores them into DB.

    Features:
    - Automatic batching (Coinbase returns max 300 candles per call)
    - Duplicate-safe upserts (idempotent)
    - Configurable granularity and duration
    - Elastic windowing (fetches oldest → newest)
    """

    MAX_CANDLES_PER_REQUEST = 300  # Coinbase API limit

    def __init__(self, db: DB):
        self.db = db
        self.coin = CoinbaseClient()

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    async def load(
        self,
        product_id: str,
        granularity: str = "ONE_MINUTE",
        *,
        start: Optional[datetime.datetime] = None,
        end: Optional[datetime.datetime] = None,
        days: Optional[int] = None,
        commit_batch: int = 500,
    ) -> int:
        """
        Load historical candles for a product.

        Args:
            product_id: e.g., "BTC-USD"
            granularity: Coinbase enum ("ONE_MINUTE", "FIVE_MINUTE", etc.)
            start / end: datetime UTC boundaries
            days: convenience mode (e.g., last 30 days)
            commit_batch: DB commit size

        Returns:
            Number of candles inserted.
        """

        # ----------------------------
        # Resolve time boundaries
        # ----------------------------
        now = datetime.datetime.now(datetime.timezone.utc)

        if end is None:
            end = now

        if start is None:
            if days is None:
                raise ValueError("Must specify either start or days")
            start = end - datetime.timedelta(days=days)

        logger.info(f"[HISTORICAL LOADER] Loading {product_id} candles:")
        logger.info(f"  granularity = {granularity}")
        logger.info(f"  start       = {start}")
        logger.info(f"  end         = {end}")

        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())

        total_inserted = 0
        batch_buffer: List[Candle] = []

        # Coinbase requires descending order, but for backtesting
        # we want chronological order. So we fetch descending, then reverse in DB.
        cursor_end = end_ts

        while cursor_end > start_ts:
            cursor_start = max(start_ts, cursor_end -
                               self._window_size_seconds(granularity))

            candles_raw = await self.coin.fetch_candles(
                product_id=product_id,
                start=cursor_start,
                end=cursor_end,
                granularity=granularity,
            )

            if not candles_raw:
                logger.warning(
                    f"[HISTORICAL LOADER] No candles for window {cursor_start}–{cursor_end}"
                )
                cursor_end = cursor_start
                continue

            asset = await self.db.get_or_create_asset(
                symbol=product_id,
                base=product_id.split("-")[0],
                quote=product_id.split("-")[1],
            )

            batch_buffer: list[Candle] = []

            for c in candles_raw:
                ts = datetime.datetime.fromtimestamp(
                    int(c["start"]), tz=datetime.timezone.utc
                )

                candle = Candle(
                    asset_id=asset.id,           # <-- NOW VALID
                    timeframe=granularity,
                    timestamp=ts,
                    open=float(c["open"]),
                    high=float(c["high"]),
                    low=float(c["low"]),
                    close=float(c["close"]),
                    volume=float(c["volume"]),
                    source="coinbase",
                )

                batch_buffer.append(candle)

            # If batch large enough → commit
            if len(batch_buffer) >= commit_batch:
                total_inserted += await self._bulk_upsert(batch_buffer)
                batch_buffer = []

            logger.info(
                f"[HISTORICAL LOADER] window {cursor_start}–{cursor_end} → {len(candles_raw)} candles"
            )

            cursor_end = cursor_start

            # Safety throttle — Coinbase rate limits aggressively
            time.sleep(0.25)

        # Final flush
        if batch_buffer:
            total_inserted += await self._bulk_upsert(batch_buffer)

        logger.info(
            f"[HISTORICAL LOADER] DONE — Inserted {total_inserted} candles")
        return total_inserted

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------

    def _window_size_seconds(self, granularity: str) -> int:
        """
        Coinbase candle limits depend on granularity.
        E.g. ONE_MINUTE → 300 minutes window per request.
        """

        mappings = {
            "ONE_MINUTE": 300 * 60,
            "FIVE_MINUTE": 300 * 5 * 60,
            "FIFTEEN_MINUTE": 300 * 15 * 60,
            "ONE_HOUR": 300 * 3600,
            "ONE_DAY": 300 * 86400,
        }

        if granularity not in mappings:
            raise ValueError(f"Unknown granularity: {granularity}")

        return mappings[granularity]

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    async def _bulk_upsert(self, candles: list[Candle]) -> int:
        if not candles:
            return 0

        rows = []
        for c in candles:
            rows.append(
                dict(
                    asset_id=c.asset_id,
                    timeframe=c.timeframe,
                    timestamp=c.timestamp,
                    open=c.open,
                    high=c.high,
                    low=c.low,
                    close=c.close,
                    volume=c.volume,
                    source=c.source,
                )
            )

        # Use your DB helper (this is already async-safe)
        await self.db.upsert_candles(rows)

        return len(rows)

