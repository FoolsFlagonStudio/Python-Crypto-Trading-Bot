from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from bot.execution.base import ExecutionEngine, ExecutionResult
from bot.persistence.models import Order
from bot.core.logger import get_logger

logger = get_logger(__name__)


class OrderManager:
    def __init__(
        self,
        db,
        execution_engine,
        portfolio_id,
        asset_id,
        strategy_config_id,
        strategy_params: dict | None = None
    ):
        self.db = db
        self.engine = execution_engine
        self.portfolio_id = portfolio_id
        self.asset_id = asset_id
        self.strategy_config_id = strategy_config_id
        self.strategy_params = strategy_params or {}

    def _compute_slippage_and_limit(self, signal_price: float, preview_price: float) -> tuple[float, float, bool]:
        """
        Returns (price_change_pct, limit_price, is_acceptable)
        """

        max_slip_pct = float(self.strategy_params.get("max_slippage_pct", 0))

        # % difference between preview & expected (signal) price
        price_change_pct = abs(
            preview_price - signal_price) / signal_price * 100

        is_ok = price_change_pct <= max_slip_pct

        # Build marketable-limit bounds
        if preview_price >= signal_price:
            # BUY — allow up to +slippage
            limit_price = signal_price * (1 + max_slip_pct / 100)
        else:
            # SELL — allow down to -slippage
            limit_price = signal_price * (1 - max_slip_pct / 100)

        return price_change_pct, limit_price, is_ok

    # ---------------------------------------------------------
    # ENTER
    # ---------------------------------------------------------
    async def handle_enter(self, price: float, timestamp: datetime):
        """
        Entry with slippage control + marketable limit orders.
        """

        # Load portfolio state
        state = await self.db.load_portfolio_state(self.portfolio_id)
        portfolio = state.portfolio

        # Get asset symbol
        async with self.db.get_session() as session:
            asset = await session.get(type(state.open_orders[0].asset), self.asset_id)

        # ---------------------------------------------------
        # Compute risk-based position size
        # ---------------------------------------------------
        equity = (
            state.last_snapshot.ending_equity
            if state.last_snapshot
            else portfolio.starting_equity
        )
        if equity is None:
            raise ValueError("Portfolio has no starting or snapshot equity.")

        max_risk = Decimal(equity) * Decimal("0.02")
        size = float(max_risk / Decimal(price))

        # ---------------------------------------------------
        # PREVIEW (get expected fill / quote price)
        # ---------------------------------------------------
        preview = await self.engine.preview(
            symbol=asset.symbol,
            side="BUY",
            size=size,
        )

        # Coinbase preview price reference
        preview_price = float(
            preview["order_configuration_preview"]["order"]["price"]
        )

        # ---------------------------------------------------
        # Slippage Validation
        # ---------------------------------------------------
        change_pct, limit_price, ok = self._compute_slippage_and_limit(
            signal_price=price,
            preview_price=preview_price,
        )

        if not ok:
            logger.warning(
                f"[SLIPPAGE BLOCKED: ENTER] preview={preview_price} signal={price} "
                f"delta={change_pct:.4f}% (max={self.strategy_params.get('max_slippage_pct')}%)"
            )
            return None

        logger.info(
            f"[ENTER] size={size:.8f} limit_price={limit_price:.4f} "
            f"(slippage {change_pct:.4f}%)"
        )

        # ---------------------------------------------------
        # Create local Order record (submitted)
        # ---------------------------------------------------
        async with self.db.get_session() as session:
            order = Order(
                portfolio_id=self.portfolio_id,
                asset_id=self.asset_id,
                strategy_config_id=self.strategy_config_id,
                side="buy",
                order_type="limit",
                size=size,
                price=limit_price,
                status="submitted",
                opened_at=timestamp,
            )
            session.add(order)
            await session.flush()

            # ---------------------------------------------------
            # Submit marketable-limit order to exchange
            # ---------------------------------------------------
            submission = await self.engine.submit(
                symbol=asset.symbol,
                side="BUY",
                size=size,
                order_type="limit",
                price=limit_price,
            )

            order.exchange_order_id = submission.exchange_order_id
            await session.commit()

        # ---------------------------------------------------
        # Poll exchange until filled / canceled
        # ---------------------------------------------------
        while True:
            result = await self.engine.poll(order.exchange_order_id)
            if result.status in ("FILLED", "CANCELLED", "REJECTED"):
                break

        # ---------------------------------------------------
        # Finalize order + create trade
        # ---------------------------------------------------
        async with self.db.get_session() as session:
            db_order = await session.get(Order, order.id)

            db_order.status = result.status
            db_order.price = result.avg_fill_price
            db_order.filled_at = datetime.now(timezone.utc)
            db_order.fee = result.fee

            # Create new Trade
            if result.status == "FILLED":
                await self.db.record_trade(
                    portfolio_id=self.portfolio_id,
                    asset_id=self.asset_id,
                    strategy_config_id=self.strategy_config_id,
                    entry_order_id=db_order.id,
                    exit_order_id=None,
                    entry_price=result.avg_fill_price,
                    exit_price=None,
                    size=result.filled_size,
                    realized_pnl=None,
                    realized_pnl_pct=None,
                    opened_at=db_order.filled_at,
                    closed_at=None,
                )

            await session.commit()

        return order

    # ---------------------------------------------------------
    # EXIT
    # ---------------------------------------------------------
    async def handle_exit(self, price: float, timestamp: datetime):
        """
        Exit with slippage control + marketable limit order.
        """

        # Load state
        state = await self.db.load_portfolio_state(self.portfolio_id)
        if not state.open_trades:
            logger.warning("EXIT signal but no open trades.")
            return None

        trade = state.open_trades[0]

        # Get asset
        async with self.db.get_session() as session:
            asset = await session.get(type(state.open_orders[0].asset), self.asset_id)

        # ---------------------------------------------------
        # PREVIEW exit price
        # ---------------------------------------------------
        preview = await self.engine.preview(
            symbol=asset.symbol,
            side="SELL",
            size=float(trade.size),
        )

        preview_price = float(
            preview["order_configuration_preview"]["order"]["price"]
        )

        # ---------------------------------------------------
        # Slippage enforcement
        # ---------------------------------------------------
        change_pct, limit_price, ok = self._compute_slippage_and_limit(
            signal_price=price,
            preview_price=preview_price,
        )

        if not ok:
            logger.warning(
                f"[SLIPPAGE BLOCKED: EXIT] preview={preview_price} signal={price} "
                f"delta={change_pct:.4f}%"
            )
            return None

        logger.info(
            f"[EXIT] size={float(trade.size):.8f} limit_price={limit_price:.4f} "
            f"(slippage {change_pct:.4f}%)"
        )

        # ---------------------------------------------------
        # Create exit Order
        # ---------------------------------------------------
        async with self.db.get_session() as session:
            order = Order(
                portfolio_id=self.portfolio_id,
                asset_id=self.asset_id,
                strategy_config_id=self.strategy_config_id,
                side="sell",
                order_type="limit",
                size=float(trade.size),
                price=limit_price,
                status="submitted",
                opened_at=timestamp,
            )
            session.add(order)
            await session.flush()

            # Submit to exchange
            submission = await self.engine.submit(
                symbol=asset.symbol,
                side="SELL",
                size=float(trade.size),
                order_type="limit",
                price=limit_price,
            )
            order.exchange_order_id = submission.exchange_order_id

            await session.commit()

        # ---------------------------------------------------
        # Poll for fill
        # ---------------------------------------------------
        while True:
            result = await self.engine.poll(order.exchange_order_id)
            if result.status in ("FILLED", "CANCELLED", "REJECTED"):
                break

        # ---------------------------------------------------
        # Finalize exit + update Trade
        # ---------------------------------------------------
        async with self.db.get_session() as session:
            db_order = await session.get(Order, order.id)

            db_order.status = result.status
            db_order.price = result.avg_fill_price
            db_order.filled_at = datetime.now(timezone.utc)
            db_order.fee = result.fee

            if result.status == "FILLED":

                realized_pnl = (result.avg_fill_price -
                                trade.entry_price) * float(trade.size)
                realized_pct = realized_pnl / \
                    (trade.entry_price * float(trade.size))

                await self.db.record_trade(
                    portfolio_id=self.portfolio_id,
                    asset_id=self.asset_id,
                    strategy_config_id=self.strategy_config_id,
                    entry_order_id=trade.entry_order_id,
                    exit_order_id=db_order.id,
                    entry_price=trade.entry_price,
                    exit_price=result.avg_fill_price,
                    size=float(trade.size),
                    realized_pnl=realized_pnl,
                    realized_pnl_pct=realized_pct,
                    opened_at=trade.opened_at,
                    closed_at=db_order.filled_at,
                    exit_reason="exit_signal",
                )

            await session.commit()

        return order
