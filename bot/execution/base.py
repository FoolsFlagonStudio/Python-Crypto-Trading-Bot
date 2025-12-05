from __future__ import annotations

from typing import Optional, Dict, Any


class ExecutionResult:
    """
    Normalized result returned by all execution engines (live or simulated).
    """

    def __init__(
        self,
        exchange_order_id: Optional[str],
        status: str,
        filled_size: float,
        avg_fill_price: Optional[float],
        fee: float,
        raw: Dict[str, Any],
    ):
        self.exchange_order_id = exchange_order_id
        self.status = status
        self.filled_size = filled_size
        self.avg_fill_price = avg_fill_price
        self.fee = fee
        self.raw = raw


class ExecutionEngine:
    """
    Abstract interface for live / simulated trading.
    """

    async def preview(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    async def submit(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> ExecutionResult:
        raise NotImplementedError

    async def poll(self, exchange_order_id: str) -> ExecutionResult:
        raise NotImplementedError
