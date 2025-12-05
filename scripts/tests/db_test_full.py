import asyncio
import selectors
from datetime import datetime, date, timezone, timedelta

from bot.persistence.db import DB


async def main():
    print("\n=== FULL DB TEST SUITE (Part 6) ===\n")
    db = DB()

    # -------------------------------
    # 1. Asset tests
    # -------------------------------
    print("\n--- Asset Tests ---")
    asset = await db.get_or_create_asset("BTC-USD", "BTC", "USD")
    print("get_or_create_asset:", asset)

    asset2 = await db.get_asset_by_symbol("BTC-USD")
    print("get_asset_by_symbol:", asset2)

    # -------------------------------
    # 2. Portfolio tests
    # -------------------------------
    print("\n--- Portfolio Tests ---")
    pf = await db.add_portfolio("Demo Portfolio", "backtest", "USD", 10_000)
    print("Created portfolio:", pf)

    loaded_pf = await db.get_portfolio(pf.id)
    print("Loaded portfolio:", loaded_pf)

    # -------------------------------
    # 3. Signals
    # -------------------------------
    print("\n--- Signal Tests ---")
    sig = await db.record_signal(
        portfolio_id=pf.id,
        asset_id=asset.id,
        strategy_config_id=None,
        signal_type="enter",
        price=42_000.12,
        extra={"strength": 0.8},
    )
    print("Recorded signal:", sig)

    # -------------------------------
    # 4. Orders + Trades
    # -------------------------------
    print("\n--- Order & Trade Tests ---")

    # Fake order insert (you will normally do this in execution module)
    from bot.persistence.models import Order

    session = await db.get_session()
    async with session:
        entry_order = Order(
            portfolio_id=pf.id,
            asset_id=asset.id,
            strategy_config_id=None,
            side="buy",
            order_type="market",
            size=0.1,
            price=42000.0,
            status="open",
            fee=0.0,
            opened_at=datetime.now(timezone.utc),
        )
        session.add(entry_order)
        await session.commit()
        await session.refresh(entry_order)

    print("Inserted entry order:", entry_order)

    # Get open orders
    open_orders = await db.get_open_orders(portfolio_id=pf.id)
    print("Open orders:", open_orders)

    # Simulate a trade
    trade = await db.record_trade(
        portfolio_id=pf.id,
        asset_id=asset.id,
        strategy_config_id=None,
        entry_order_id=entry_order.id,
        exit_order_id=None,
        entry_price=42000.0,
        exit_price=None,
        size=0.1,
        realized_pnl=None,
        realized_pnl_pct=None,
        opened_at=datetime.now(timezone.utc),
        closed_at=None,
        exit_reason=None,
    )
    print("Recorded trade:", trade)

    # -------------------------------
    # 5. Daily Snapshot
    # -------------------------------
    print("\n--- Snapshot Tests ---")
    snap = await db.record_snapshot(
        portfolio_id=pf.id,
        date_=date.today(),
        starting_equity=10_000,
        ending_equity=10_150,
        realized_pnl=150,
        unrealized_pnl=0,
        num_trades=1,
        num_winning_trades=1,
        num_losing_trades=0,
        max_intraday_drawdown=20,
        day_label="green",
    )
    print("Recorded snapshot:", snap)

    last_snap = await db.load_last_snapshot(pf.id)
    print("load_last_snapshot:", last_snap)

    # -------------------------------
    # 6. Error Logging
    # -------------------------------
    print("\n--- Error Log Tests ---")
    err = await db.record_error(
        context="test_suite",
        message="Something bad happened!",
        stacktrace="Fake stacktrace...",
    )
    print("Recorded error:", err)

    # -------------------------------
    # 7. Bulk Candle Inserts
    # -------------------------------
    print("\n--- Candle Insert Tests ---")

    candles = [
        {
            "asset_id": asset.id,
            "timeframe": "1h",
            "timestamp": datetime.now(timezone.utc) - timedelta(hours=i),
            "open": 42000 + i,
            "high": 42100 + i,
            "low": 41900 + i,
            "close": 42050 + i,
            "volume": 10_000 + i * 100,
            "source": "test",
        }
        for i in range(3)
    ]

    print("Inserting 3 candles...")
    await db.insert_candles(candles)
    print("Insert complete.")

    # Test upsert (modify the last candle)
    print("Upserting candle...")
    candles[-1]["close"] = candles[-1]["close"] + 100
    candles[-1]["volume"] += 500
    await db.upsert_candles([candles[-1]])
    print("Upsert complete.")

    # -------------------------------
    # 8. Portfolio State Loader
    # -------------------------------
    print("\n--- Portfolio State ---")
    state = await db.load_portfolio_state(pf.id)
    print("PortfolioState:")
    print("  portfolio:", state.portfolio)
    print("  open_orders:", state.open_orders)
    print("  open_trades:", state.open_trades)
    print("  last_snapshot:", state.last_snapshot)

    print("\n=== ALL TESTS COMPLETED SUCCESSFULLY ===\n")


if __name__ == "__main__":
    # Fix Psycopg Windows event loop
    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())