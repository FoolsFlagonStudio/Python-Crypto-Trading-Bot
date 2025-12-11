from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from contextlib import asynccontextmanager

from .engine import async_session_maker
from .models import (
    Asset,
    Portfolio,
    Order,
    Trade,
    DailySnapshot,
    Candle,
    Signal,
    RiskEvent,
    ErrorLog,
)

# -------------------------------------------------------------------
# Helper types / constants
# -------------------------------------------------------------------

OPEN_ORDER_STATUSES = ("open", "pending", "partially_filled")


@dataclass
class PortfolioState:
    """Lightweight aggregate of a portfolio's state for strategy/risk modules."""
    portfolio: Portfolio | None
    open_orders: list[Order]
    open_trades: list[Trade]
    last_snapshot: DailySnapshot | None


# -------------------------------------------------------------------
# DB Facade
# -------------------------------------------------------------------


class DB:
    """
    Persistence API for the trading bot.
    This class is the *only* place that should touch SQLAlchemy sessions
    in the rest of the application. Strategies, risk modules, and
    execution logic call into here instead of writing raw queries.
    """

    def __init__(self):
        pass

    # ---------------------------------------------------------------
    # Timestamp normalization helper
    # ---------------------------------------------------------------
    def _normalize_dt(self, dt: datetime | None) -> datetime:
        """Ensure all timestamps are timezone-aware UTC."""
        if dt is None:
            return datetime.now(timezone.utc)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    # ---------------------------------------------------------------
    # Session primitive
    # ---------------------------------------------------------------
    @asynccontextmanager
    async def get_session(self):
        session = async_session_maker()
        try:
            yield session
        finally:
            await session.close()

    # ---------------------------------------------------------------
    # Asset helpers
    # ---------------------------------------------------------------

    async def add_asset(self, symbol: str, base: str | None, quote: str | None) -> Asset:
        async with async_session_maker() as session:
            asset = Asset(
                symbol=symbol,
                base_asset=base,
                quote_asset=quote,
            )
            try:
                session.add(asset)
                await session.commit()
                await session.refresh(asset)
                return asset
            except:  # noqa: E722
                await session.rollback()
                raise

    async def get_asset_by_symbol(self, symbol: str) -> Asset | None:
        async with async_session_maker() as session:
            result = await session.execute(
                select(Asset).where(Asset.symbol == symbol)
            )
            return result.scalars().first()

    async def get_or_create_asset(
        self,
        symbol: str,
        base: str | None = None,
        quote: str | None = None,
    ) -> Asset:

        async with async_session_maker() as session:
            result = await session.execute(
                select(Asset).where(Asset.symbol == symbol)
            )
            asset = result.scalars().first()
            if asset:
                return asset

            asset = Asset(
                symbol=symbol,
                base_asset=base,
                quote_asset=quote,
            )
            try:
                session.add(asset)
                await session.commit()
                await session.refresh(asset)
                return asset
            except:  # noqa: E722
                await session.rollback()
                raise

    # ---------------------------------------------------------------
    # Portfolio helpers
    # ---------------------------------------------------------------

    async def add_portfolio(
        self,
        name: str,
        mode: str,
        base_currency: str,
        starting_equity: float | None = None,
    ) -> Portfolio:
        async with async_session_maker() as session:
            portfolio = Portfolio(
                name=name,
                mode=mode,
                base_currency=base_currency,
                starting_equity=starting_equity,
            )
            try:
                session.add(portfolio)
                await session.commit()
                await session.refresh(portfolio)
                return portfolio
            except:  # noqa: E722
                await session.rollback()
                raise

    async def get_portfolio(self, portfolio_id: int) -> Portfolio | None:
        async with async_session_maker() as session:
            result = await session.execute(
                select(Portfolio).where(Portfolio.id == portfolio_id)
            )
            return result.scalars().first()

    async def load_last_snapshot(
        self,
        portfolio_id: int,
    ) -> DailySnapshot | None:

        async with async_session_maker() as session:
            result = await session.execute(
                select(DailySnapshot)
                .where(DailySnapshot.portfolio_id == portfolio_id)
                .order_by(DailySnapshot.date.desc())
                .limit(1)
            )
            return result.scalars().first()

    async def load_portfolio_state(
        self,
        portfolio_id: int,
    ) -> PortfolioState:

        async with async_session_maker() as session:
            pf_result = await session.execute(
                select(Portfolio).where(Portfolio.id == portfolio_id)
            )
            portfolio = pf_result.scalars().first()

            # If no portfolio exists, return an "empty" state instead of None
            if portfolio is None:
                return PortfolioState(
                    portfolio=None,
                    open_orders=[],
                    open_trades=[],
                    last_snapshot=None,
                )

            orders_result = await session.execute(
                select(Order).where(
                    Order.portfolio_id == portfolio_id,
                    Order.status.in_(OPEN_ORDER_STATUSES),
                )
            )
            open_orders = list(orders_result.scalars().all())

            trades_result = await session.execute(
                select(Trade).where(
                    Trade.portfolio_id == portfolio_id,
                    Trade.closed_at.is_(None),
                )
            )
            open_trades = list(trades_result.scalars().all())

            snapshot_result = await session.execute(
                select(DailySnapshot)
                .where(DailySnapshot.portfolio_id == portfolio_id)
                .order_by(DailySnapshot.date.desc())
                .limit(1)
            )
            last_snapshot = snapshot_result.scalars().first()

            return PortfolioState(
                portfolio=portfolio,
                open_orders=open_orders,
                open_trades=open_trades,
                last_snapshot=last_snapshot,
            )

    # ---------------------------------------------------------------
    # Order helpers
    # ---------------------------------------------------------------

    async def get_open_orders(
        self,
        portfolio_id: int | None = None,
        asset_id: int | None = None,
    ) -> list[Order]:

        async with async_session_maker() as session:
            stmt = select(Order).where(
                Order.status.in_(OPEN_ORDER_STATUSES)
            )
            if portfolio_id is not None:
                stmt = stmt.where(Order.portfolio_id == portfolio_id)
            if asset_id is not None:
                stmt = stmt.where(Order.asset_id == asset_id)

            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_unfilled_orders(
        self,
        portfolio_id: int | None = None,
    ) -> list[Order]:

        async with async_session_maker() as session:
            stmt = select(Order).where(Order.filled_at.is_(None))
            # Exclude hard-canceled orders if you use a 'canceled' status.
            stmt = stmt.where(Order.status != "canceled")

            if portfolio_id is not None:
                stmt = stmt.where(Order.portfolio_id == portfolio_id)

            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ---------------------------------------------------------------
    # Utility inserts: signals, trades, snapshots, errors
    # ---------------------------------------------------------------

    async def record_signal(
        self,
        portfolio_id: int,
        asset_id: int,
        strategy_config_id: int | None,
        signal_type: str,
        price: float | None,
        extra: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> Signal:

        timestamp = self._normalize_dt(timestamp)

        async with async_session_maker() as session:
            signal = Signal(
                portfolio_id=portfolio_id,
                asset_id=asset_id,
                strategy_config_id=strategy_config_id,
                timestamp=timestamp,
                signal_type=signal_type,
                price=price,
                extra=extra,
            )
            try:
                session.add(signal)
                await session.commit()
            except:  # noqa: E722
                await session.rollback()
                raise

            await session.refresh(signal)
            return signal

    async def record_trade(
        self,
        portfolio_id: int,
        asset_id: int,
        strategy_config_id: int | None,
        entry_order_id: int,
        exit_order_id: int | None,
        entry_price: float | None,
        exit_price: float | None,
        size: float | None,
        realized_pnl: float | None,
        realized_pnl_pct: float | None,
        opened_at: datetime | None,
        closed_at: datetime | None,
        exit_reason: str | None = None,
    ) -> Trade:

        opened_at = self._normalize_dt(opened_at)
        closed_at = self._normalize_dt(closed_at) if closed_at else None

        async with async_session_maker() as session:
            trade = Trade(
                portfolio_id=portfolio_id,
                asset_id=asset_id,
                strategy_config_id=strategy_config_id,
                entry_order_id=entry_order_id,
                exit_order_id=exit_order_id,
                entry_price=entry_price,
                exit_price=exit_price,
                size=size,
                realized_pnl=realized_pnl,
                realized_pnl_pct=realized_pnl_pct,
                opened_at=opened_at,
                closed_at=closed_at,
                exit_reason=exit_reason,
            )
            try:
                session.add(trade)
                await session.commit()
            except:  # noqa: E722
                await session.rollback()
                raise

            await session.refresh(trade)
            return trade

    async def record_snapshot(
        self,
        portfolio_id: int,
        date_,
        starting_equity: float | None = None,
        ending_equity: float | None = None,
        realized_pnl: float | None = None,
        unrealized_pnl: float | None = None,
        deposits_withdrawals: float | None = None,
        num_trades: int | None = None,
        num_winning_trades: int | None = None,
        num_losing_trades: int | None = None,
        max_intraday_drawdown: float | None = None,
        day_label: str | None = None,
    ) -> DailySnapshot:

        async with async_session_maker() as session:
            snapshot = DailySnapshot(
                portfolio_id=portfolio_id,
                date=date_,
                starting_equity=starting_equity,
                ending_equity=ending_equity,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                deposits_withdrawals=deposits_withdrawals,
                num_trades=num_trades,
                num_winning_trades=num_winning_trades,
                num_losing_trades=num_losing_trades,
                max_intraday_drawdown=max_intraday_drawdown,
                day_label=day_label,
            )
            try:
                session.add(snapshot)
                await session.commit()
                await session.refresh(snapshot)
                return snapshot
            except:  # noqa: E722
                await session.rollback()
                raise

    async def record_error(
        self,
        context: str,
        message: str,
        stacktrace: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ErrorLog:

        occurred_at = self._normalize_dt(occurred_at)

        async with async_session_maker() as session:
            err = ErrorLog(
                context=context,
                message=message,
                stacktrace=stacktrace,
                occurred_at=occurred_at,
            )
            try:
                session.add(err)
                await session.commit()
            except:  # noqa: E722
                await session.rollback()
                raise

            await session.refresh(err)
            return err

    async def record_risk_event(
        self,
        portfolio_id: int,
        event_type: str,
        details: dict[str, Any] | None = None,
        triggered_at: datetime | None = None,
    ) -> RiskEvent:
        """
        Persist a RiskEvent row. Used by the RiskManager when any
        risk rule triggers (veto or soft warning-worthy conditions).
        """
        triggered_at = self._normalize_dt(triggered_at)

        async with async_session_maker() as session:
            evt = RiskEvent(
                portfolio_id=portfolio_id,
                event_type=event_type,
                details=details,
                triggered_at=triggered_at,
            )
            try:
                session.add(evt)
                await session.commit()
            except:  # noqa: E722
                await session.rollback()
                raise

            await session.refresh(evt)
            return evt

    # ---------------------------------------------------------------
    # Bulk operations: candles
    # ---------------------------------------------------------------

    async def insert_candles(
        self,
        candles: Iterable[dict[str, Any]],
    ) -> None:

        candles = list(candles)
        if not candles:
            return

        async with async_session_maker() as session:
            stmt = pg_insert(Candle).values(candles)
            await session.execute(stmt)
            await session.commit()

    async def upsert_candles(
        self,
        candles: Iterable[dict[str, Any]],
    ) -> None:

        candles = list(candles)
        if not candles:
            return

        async with async_session_maker() as session:
            stmt = pg_insert(Candle).values(candles)

            update_cols = {
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "source": stmt.excluded.source,
            }

            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    Candle.asset_id,
                    Candle.timeframe,
                    Candle.timestamp,
                ],
                set_=update_cols,
            )

            await session.execute(stmt)
            await session.commit()
