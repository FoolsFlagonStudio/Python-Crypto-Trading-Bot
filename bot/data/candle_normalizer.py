from typing import List, Dict


def normalize_coinbase_candles(
    raw: List[Dict],
    asset_id: int,
    timeframe: str,
    source: str = "coinbase",
) -> List[Dict]:
    """
    Convert Coinbase OHLCV candle dicts into DB-insertable rows.
    """

    rows = []
    for c in raw:
        rows.append(
            {
                "asset_id": asset_id,
                "timeframe": timeframe,
                "timestamp": c["timestamp"],
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"],
                "source": source,
            }
        )
    return rows
