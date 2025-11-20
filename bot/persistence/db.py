from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession

from .engine import async_session_maker
from .models import Asset, Portfolio


class DB:
    """Lightweight database abstraction for inserts/queries."""

    def __init__(self):
        pass

    async def get_session(self) -> AsyncSession:
        return async_session_maker()

    async def add_asset(self, symbol: str, base: str | None, quote: str | None):
        async with async_session_maker() as session:
            asset = Asset(
                symbol=symbol,
                base_asset=base,
                quote_asset=quote,
            )
            session.add(asset)
            await session.commit()
            await session.refresh(asset)
            return asset

    async def get_asset_by_symbol(self, symbol: str) -> Asset | None:
        async with async_session_maker() as session:
            result = await session.execute(
                Asset.__table__.select().where(Asset.symbol == symbol)
            )
            row = result.first()
            return row[0] if row else None

    async def add_portfolio(self, name: str, mode: str, base_currency: str):
        async with async_session_maker() as session:
            portfolio = Portfolio(
                name=name,
                mode=mode,
                base_currency=base_currency,
            )
            session.add(portfolio)
            await session.commit()
            await session.refresh(portfolio)
            return portfolio
