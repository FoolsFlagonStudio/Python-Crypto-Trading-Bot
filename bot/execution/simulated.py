from __future__ import annotations

from typing import Optional, Dict, Any
from datetime import datetime, timezone

from bot.execution.base import ExecutionEngine, ExecutionResult


class SimulatedExecutionEngine(ExecutionEngine):
    """
    Paper-trading / backtest execution engine.

    - No real API calls
    - Immediate fills
    - Optional simple fee model
    """

    def __init__(self, fee_bps: float = 5.0):
        # fee in basis points of notional, e.g. 5 bps = 0.05%
        self.fee_bps = fee_bps
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._next_id = 1

    def _new_order_id(self) -> str:
        oid = f"sim-{self._next_id}"
        self._next_id += 1
        return oid

    async def preview(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Simple preview that just echoes back a 'price'.
        For paper mode we treat `price` as the expected execution price.
        If price is None, caller should fall back to signal price.
        """
        # shape is chosen to match what handle_enter/exit expect
        return {
            "order_configuration_preview": {
                "order": {
                    "price": price  # may be None, caller must handle fallback
                }
            },
            "simulated": True,
        }

    async def submit(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> ExecutionResult:
        """
        Simulate immediate submission; actual fill will be handled in poll().
        """
        order_id = self._new_order_id()
        # store minimal state
        self._orders[order_id] = {
            "symbol": symbol,
            "side": side.lower(),
            "size": float(size),
            "order_type": order_type,
            "price": float(price) if price is not None else None,
            "status": "SUBMITTED",
            "created_at": datetime.now(timezone.utc),
        }

        return ExecutionResult(
            exchange_order_id=order_id,
            status="SUBMITTED",
            filled_size=0.0,
            avg_fill_price=None,
            fee=0.0,
            raw={"simulated": True, "order_id": order_id},
        )

    async def poll(self, exchange_order_id: str) -> ExecutionResult:
        """
        For now: instant fill at the limit/market price with simple fee.
        """
        order = self._orders.get(exchange_order_id)
        if not order:
            # unknown order, mark as rejected
            return ExecutionResult(
                exchange_order_id=exchange_order_id,
                status="REJECTED",
                filled_size=0.0,
                avg_fill_price=None,
                fee=0.0,
                raw={"error": "unknown_sim_order"},
            )

        # Simulate immediate full fill
        price = order["price"] or 0.0
        size = order["size"]
        notional = price * size
        fee = abs(notional) * (self.fee_bps / 10_000.0)

        order["status"] = "FILLED"

        return ExecutionResult(
            exchange_order_id=exchange_order_id,
            status="FILLED",
            filled_size=size,
            avg_fill_price=price,
            fee=fee,
            raw={"simulated": True, "order_id": exchange_order_id},
        )
