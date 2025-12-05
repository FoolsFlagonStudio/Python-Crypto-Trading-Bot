from __future__ import annotations

from coinbase.rest import RESTClient
from bot.execution.base import ExecutionEngine, ExecutionResult


class LiveCoinbaseExecutionEngine(ExecutionEngine):
    def __init__(self, api_key: str, api_secret: str):
        self.client = RESTClient(api_key=api_key, api_secret=api_secret)

    # ---------------------------------------------------------
    # PREVIEW
    # ---------------------------------------------------------
    async def preview(self, symbol, side, size, order_type="market", price=None):
        product_id = symbol  # ex: "BTC-USD"

        if order_type == "market":
            config = {
                "preview_market": {
                    "base_size": str(size)
                }
            }
        else:
            raise NotImplementedError("Only market preview supported.")

        resp = self.client.orders.preview_order(
            product_id=product_id,
            side=side.lower(),
            order_configuration=config
        )
        return resp

    # ---------------------------------------------------------
    # SUBMIT ORDER
    # ---------------------------------------------------------
    async def submit(self, symbol, side, size, order_type="market", price=None):
        product_id = symbol

        if order_type == "market":
            config = {
                "market_market_ioc": {
                    "base_size": str(size)
                }
            }
        else:
            raise NotImplementedError("Only market orders supported.")

        resp = self.client.orders.create_order(
            product_id=product_id,
            side=side.lower(),
            order_configuration=config,
        )

        order_id = resp.get("order_id")

        return ExecutionResult(
            exchange_order_id=order_id,
            status="SUBMITTED",
            filled_size=0,
            avg_fill_price=None,
            fee=0,
            raw=resp,
        )

    # ---------------------------------------------------------
    # POLL
    # ---------------------------------------------------------
    async def poll(self, exchange_order_id: str):
        resp = self.client.orders.get_order(order_id=exchange_order_id)

        fills = resp.get("fills", []) or []
        filled_size = sum(float(f["size"]) for f in fills)
        total_cost = sum(float(f["price"]) * float(f["size"]) for f in fills)
        total_fee = sum(float(f.get("fee", 0)) for f in fills)

        avg_price = (total_cost / filled_size) if filled_size > 0 else None

        return ExecutionResult(
            exchange_order_id=exchange_order_id,
            status=resp.get("status"),
            filled_size=filled_size,
            avg_fill_price=avg_price,
            fee=total_fee,
            raw=resp,
        )
