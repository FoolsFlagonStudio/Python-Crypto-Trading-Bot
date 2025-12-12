from __future__ import annotations
import datetime
import time
from typing import List, Optional

from bot.data.coinbase_client import CoinbaseClient
from bot.persistence.db import DB
from bot.persistence.models import Candle
from bot.core.logger import get_logger

logger = get_logger(__name__)


class HistoricalLoader:
    """
    Loads historical candles from Coinbase Advanced API and stores them into DB.

    Now supports:
    - Full resets (delete old candle history)
    - Flexible date ranges (days, start/end)
    - Large multi-month backfills
    """

    MAX_CANDLES_PER_REQUEST = 300  # Coinbase API limit

    def __init__(self, db: DB):
        self.db = db
        self.coin = CoinbaseClient()

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
        reset_existing: bool = False,     # <-- NEW
    ) -> int:

        now = datetime.datetime.now(datetime.timezone.utc)
        if end is None:
            end = now

        if start is None:
            if days is None:
                raise ValueError("Must specify either start or days")
            start = end - datetime.timedelta(days=days)

        logger.info(f"[HISTORICAL LOADER] Loading {product_id} {granularity}")
        logger.info(f"  start       = {start}")
        logger.info(f"  end         = {end}")

        # Ensure asset exists
        asset = await self.db.get_or_create_asset(
            symbol=product_id,
            base=product_id.split("-")[0],
            quote=product_id.split("-")[1],
        )

        # ----------------------------------------------------
        # OPTIONAL: Reset existing candles for clean backfills
        # ----------------------------------------------------
        if reset_existing:
            logger.warning(
                f"[HISTORICAL LOADER] RESET ENABLED — deleting old candles for {product_id}"
            )
            async with self.db.get_session() as session:
                await session.execute(
                    Candle.__table__.delete().where(
                        (Candle.asset_id == asset.id) &
                        (Candle.timeframe == granularity)
                    )
                )
                await session.commit()

        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())

        total_inserted = 0
        batch_buffer: List[Candle] = []

        # FETCH IN REVERSE WINDOWS (Coinbase requirement)
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
                    f"[HISTORICAL LOADER] No candles {cursor_start}–{cursor_end}"
                )
                cursor_end = cursor_start
                continue

            # Transform → Candle objects
            for c in candles_raw:
                ts = datetime.datetime.fromtimestamp(
                    int(c["start"]), tz=datetime.timezone.utc)

                batch_buffer.append(
                    Candle(
                        asset_id=asset.id,
                        timeframe=granularity,
                        timestamp=ts,
                        open=float(c["open"]),
                        high=float(c["high"]),
                        low=float(c["low"]),
                        close=float(c["close"]),
                        volume=float(c["volume"]),
                        source="coinbase",
                    )
                )

            # Commit batch
            if len(batch_buffer) >= commit_batch:
                total_inserted += await self._bulk_upsert(batch_buffer)
                batch_buffer = []

            logger.info(
                f"[HISTORICAL LOADER] {cursor_start}–{cursor_end} → {len(candles_raw)} candles"
            )

            cursor_end = cursor_start
            time.sleep(0.25)  # rate limit protection

        # Final commit
        if batch_buffer:
            total_inserted += await self._bulk_upsert(batch_buffer)

        logger.info(
            f"[HISTORICAL LOADER] DONE — Inserted {total_inserted} candles")
        return total_inserted

    # ----------------------------------------------------------------------
    def _window_size_seconds(self, granularity: str) -> int:
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

    # ----------------------------------------------------------------------
    async def _bulk_upsert(self, candles: list[Candle]) -> int:
        if not candles:
            return 0

        rows = [
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
            for c in candles
        ]

        await self.db.upsert_candles(rows)
        return len(rows)
