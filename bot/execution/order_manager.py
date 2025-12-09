from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from bot.execution.base import ExecutionEngine, ExecutionResult
from bot.persistence.models import Order
from bot.core.logger import get_logger
from bot.persistence.models import Order, Trade, Asset
from bot.execution.simulated import SimulatedExecutionEngine


logger = get_logger(__name__)


class OrderManager:
    def __init__(
        self,
        db,
        execution_engine,
        portfolio_id: int,
        asset_id: int,
        strategy_config_id: int,
        strategy_params: dict,
    ):
        self.db = db
        self.engine = execution_engine
        self.portfolio_id = portfolio_id
        self.asset_id = asset_id
        self.strategy_config_id = strategy_config_id
        self.strategy_params = strategy_params

        # Derive mode from engine type
        self.mode = "paper" if isinstance(execution_engine, SimulatedExecutionEngine) else "live"

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

    async def handle_enter(self, price: float, timestamp: datetime, candle=None):
        """
        Entry with slippage control + marketable limit orders + analytics metadata.
        """

        # Load portfolio state
        state = await self.db.load_portfolio_state(self.portfolio_id)
        portfolio = state.portfolio

        # Get asset symbol
        async with self.db.get_session() as session:
            asset = await session.get(Asset, self.asset_id)

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
        # PREVIEW (expected fill / quote price)
        # ---------------------------------------------------
        preview = await self.engine.preview(
            symbol=asset.symbol,
            side="BUY",
            size=size,
        )

        # Coinbase-style preview price
        preview_price = (
            preview.get("order_configuration_preview", {})
            .get("order", {})
            .get("price")
        )

        if preview_price is None:
            # fallback: assume no slippage vs signal price in sim mode
            preview_price = price

        preview_price = float(preview_price)

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
        # Finalize order + create Trade
        # ---------------------------------------------------
        async with self.db.get_session() as session:
            db_order = await session.get(Order, order.id)

            db_order.status = result.status
            db_order.price = result.avg_fill_price
            db_order.filled_at = datetime.now(timezone.utc)
            db_order.fee = result.fee

            if result.status == "FILLED":

                # -------------------------------
                # Initial Trade Metadata
                # -------------------------------
                volatility = None
                if candle:
                    volatility = float(candle.high - candle.low) / candle.close

                initial_tags = {
                    "entry_reason": "signal",
                    "volatility_at_entry": volatility,
                    "mfe": 0.0,
                    "mae": 0.0,
                    "max_runup_pct": 0.0,
                    "max_drawdown_pct": 0.0,
                    "entry_timestamp": timestamp.isoformat(),
                }

                # Create Trade row with metadata
                trade = await self.db.record_trade(
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

                # Save metadata
                db_trade = await session.get(type(trade), trade.id)
                db_trade.analytics = initial_tags

            await session.commit()

        return order

    # ---------------------------------------------------------
    # EXIT
    # ---------------------------------------------------------
    async def handle_exit(self, price: float, timestamp: datetime, auto_reason: str | None = None):
        """
        Exit with slippage control + marketable limit order.
        """

        # Load state
        state = await self.db.load_portfolio_state(self.portfolio_id)
        if not state.open_trades:
            logger.warning("EXIT signal but no open trades.")
            return None

        trade = state.open_trades[0]

        # Get asset directly
        async with self.db.get_session() as session:
            asset = await session.get(Asset, self.asset_id)

        # ---------------------------------------------------
        # PREVIEW exit price
        # ---------------------------------------------------
        preview = await self.engine.preview(
            symbol=asset.symbol,
            side="SELL",
            size=float(trade.size),
        )

        # Try to pull a preview price; if it's missing/None, fall back to the signal price
        raw_price = None
        try:
            raw_price = (
                preview.get("order_configuration_preview", {})
                .get("order", {})
                .get("price")
            )
        except AttributeError:
            # preview or nested dicts weren't dict-like; ignore and fall back
            raw_price = None

        if raw_price is None:
            preview_price = float(price)
        else:
            preview_price = float(raw_price)

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
                is_simulated=self.mode == "paper",
            )
            session.add(order)
            await session.flush()

            # Submit to exchange / paper engine
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
                # Normalize to Decimal
                entry_price_dec = trade.entry_price
                exit_price_dec = Decimal(str(result.avg_fill_price))
                size_dec = trade.size or Decimal("0")

                if entry_price_dec and size_dec:
                    realized_pnl_dec = (
                        exit_price_dec - entry_price_dec) * size_dec
                    realized_pnl = float(realized_pnl_dec)
                    realized_pct = float(
                        realized_pnl_dec / (entry_price_dec * size_dec)
                    )
                else:
                    realized_pnl = None
                    realized_pct = None

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
                    exit_reason=auto_reason or "exit_signal",
                )

                # ---- Update analytics JSON on the trade ----
                meta = trade.analytics or {}

                opened = trade.opened_at
                closed = db_order.filled_at
                if opened and closed:
                    meta["time_in_trade_seconds"] = (
                        closed - opened).total_seconds()

                meta["exit_trigger"] = auto_reason or "exit_signal"

                async with self.db.get_session() as session2:
                    db_trade = await session2.get(type(trade), trade.id)
                    db_trade.analytics = meta
                    await session2.commit()

            await session.commit()

        return order

    async def check_auto_exits(self, candle):
        """
        Called every candle (or tick) to check:
        - stop-loss hit
        - take-profit hit

        If either triggers → place exit order automatically.
        """

        state = await self.db.load_portfolio_state(self.portfolio_id)
        if not state.open_trades:
            return None  # no open positions

        trade = state.open_trades[0]

        stop_loss_pct = float(self.strategy_params.get("stop_loss_pct", 0))
        take_profit_pct = float(self.strategy_params.get("take_profit_pct", 0))

        if stop_loss_pct == 0 and take_profit_pct == 0:
            return None  # no auto-exit logic enabled

        entry_price = float(trade.entry_price)
        current_price = float(candle.close)

        # Calculate thresholds
        sl_trigger = entry_price * (1 - stop_loss_pct / 100)
        tp_trigger = entry_price * (1 + take_profit_pct / 100)

        # Check SL
        if stop_loss_pct > 0 and current_price <= sl_trigger:
            logger.info(
                f"[AUTO STOP LOSS] price={current_price} <= {sl_trigger} "
                f"({stop_loss_pct}% below entry)"
            )
            return await self.handle_exit(
                price=current_price,
                timestamp=candle.timestamp,
                auto_reason="stop_loss"
            )

        # Check TP
        if take_profit_pct > 0 and current_price >= tp_trigger:
            logger.info(
                f"[AUTO TAKE PROFIT] price={current_price} >= {tp_trigger} "
                f"({take_profit_pct}% above entry)"
            )
            return await self.handle_exit(
                price=current_price,
                timestamp=candle.timestamp,
                auto_reason="take_profit"
            )

        return None

    async def update_trade_tracking_each_candle(self, candle):
        """
        Called every candle to update MFE/MAE + drawdown stats on open trades.
        """

        state = await self.db.load_portfolio_state(self.portfolio_id)
        if state is None:
            return
        if not state.open_trades:
            return None

        trade = state.open_trades[0]
        current = float(candle.close)
        entry = float(trade.entry_price)

        pct_change = (current - entry) / entry

        meta = trade.analytics or {}

        # Update MFE / MAE
        meta["mfe"] = max(meta.get("mfe", 0.0), pct_change)
        meta["mae"] = min(meta.get("mae", 0.0), pct_change)

        # Run-up and drawdown
        meta["max_runup_pct"] = meta["mfe"]
        meta["max_drawdown_pct"] = meta["mae"]

        # Save metadata back to DB
        async with self.db.get_session() as session:
            db_trade = await session.get(type(trade), trade.id)
            db_trade.analytics = meta
            await session.commit()

        return meta
