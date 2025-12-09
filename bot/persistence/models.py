from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
    JSON,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


# ============================================================
# Base Declarative Class
# ============================================================

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


# ============================================================
# Asset Table
# ============================================================

class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    base_asset: Mapped[Optional[str]] = mapped_column(String)
    quote_asset: Mapped[Optional[str]] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    orders: Mapped[List["Order"]] = relationship(back_populates="asset")
    trades: Mapped[List["Trade"]] = relationship(back_populates="asset")
    candles: Mapped[List["Candle"]] = relationship(back_populates="asset")

    def __repr__(self) -> str:
        return f"<Asset {self.symbol}>"


# ============================================================
# Portfolios
# ============================================================

class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String)  # live | backtest | paper
    starting_equity: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    base_currency: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    orders: Mapped[List["Order"]] = relationship(back_populates="portfolio")
    trades: Mapped[List["Trade"]] = relationship(back_populates="portfolio")
    snapshots: Mapped[List["DailySnapshot"]] = relationship(
        back_populates="portfolio"
    )
    signals: Mapped[List["Signal"]] = relationship(
        back_populates="portfolio"
    )
    risk_events: Mapped[List["RiskEvent"]] = relationship(
        back_populates="portfolio"
    )
    backtest_runs: Mapped[List["BacktestRun"]] = relationship(
        back_populates="portfolio"
    )

    def __repr__(self) -> str:
        return f"<Portfolio {self.name}>"


# ============================================================
# Strategy Configs
# ============================================================

class StrategyConfig(Base):
    __tablename__ = "strategy_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    params_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    active_from: Mapped[Optional[datetime]
                        ] = mapped_column(DateTime(timezone=True))
    active_to: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    orders: Mapped[List["Order"]] = relationship(
        back_populates="strategy_config")
    trades: Mapped[List["Trade"]] = relationship(
        back_populates="strategy_config")
    signals: Mapped[List["Signal"]] = relationship(
        back_populates="strategy_config")
    backtest_runs: Mapped[List["BacktestRun"]] = relationship(
        back_populates="strategy_config"
    )


# ============================================================
# Orders
# ============================================================

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id"), nullable=False)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id"), nullable=False)
    strategy_config_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("strategy_configs.id")
    )

    side: Mapped[str] = mapped_column(String, nullable=False)  # buy | sell
    order_type: Mapped[Optional[str]] = mapped_column(
        String)   # market | limit | stop

    size: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    price: Mapped[Optional[float]] = mapped_column(Numeric(18, 8))

    status: Mapped[Optional[str]] = mapped_column(String)
    exchange_order_id: Mapped[Optional[str]] = mapped_column(String)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    fee: Mapped[float] = mapped_column(Numeric(18, 8), default=0)

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)
    filled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True))
    canceled_at: Mapped[Optional[datetime]
                        ] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # relationships
    portfolio: Mapped["Portfolio"] = relationship(back_populates="orders")
    asset: Mapped["Asset"] = relationship(back_populates="orders")
    strategy_config: Mapped["StrategyConfig"] = relationship(
        back_populates="orders"
    )

    entry_trade: Mapped[Optional["Trade"]] = relationship(
        back_populates="entry_order",
        foreign_keys="Trade.entry_order_id",
        uselist=False,
    )
    exit_trade: Mapped[Optional["Trade"]] = relationship(
        back_populates="exit_order",
        foreign_keys="Trade.exit_order_id",
        uselist=False,
    )


# ============================================================
# Trades
# ============================================================

class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)

    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    strategy_config_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("strategy_configs.id")
    )

    entry_order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), nullable=False)
    exit_order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("orders.id"))

    entry_price: Mapped[Optional[float]] = mapped_column(Numeric(18, 8))
    exit_price: Mapped[Optional[float]] = mapped_column(Numeric(18, 8))

    size: Mapped[Optional[float]] = mapped_column(Numeric(28, 10))
    realized_pnl: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    realized_pnl_pct: Mapped[Optional[float]] = mapped_column(Numeric(9, 4))

    opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True))

    exit_reason: Mapped[Optional[str]] = mapped_column(String)
    analytics: Mapped[Optional[Dict[str, Any]]
                     ] = mapped_column(JSON, default={})

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # relationships
    portfolio: Mapped["Portfolio"] = relationship(back_populates="trades")
    asset: Mapped["Asset"] = relationship(back_populates="trades")
    strategy_config: Mapped["StrategyConfig"] = relationship(
        back_populates="trades"
    )

    entry_order: Mapped["Order"] = relationship(
        back_populates="entry_trade",
        foreign_keys=[entry_order_id],
    )
    exit_order: Mapped[Optional["Order"]] = relationship(
        back_populates="exit_trade",
        foreign_keys=[exit_order_id],
    )


# ============================================================
# Daily Snapshots
# ============================================================

class DailySnapshot(Base):
    __tablename__ = "daily_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    date: Mapped[date] = mapped_column(Date, nullable=False)

    starting_equity: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    ending_equity: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    realized_pnl: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    unrealized_pnl: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    deposits_withdrawals: Mapped[Optional[float]
                                 ] = mapped_column(Numeric(18, 4))

    num_trades: Mapped[Optional[int]] = mapped_column(Integer)
    num_winning_trades: Mapped[Optional[int]] = mapped_column(Integer)
    num_losing_trades: Mapped[Optional[int]] = mapped_column(Integer)

    max_intraday_drawdown: Mapped[Optional[float]
                                  ] = mapped_column(Numeric(18, 4))
    day_label: Mapped[Optional[str]] = mapped_column(
        String)  # green | red | flat

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    portfolio: Mapped["Portfolio"] = relationship(back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint("portfolio_id", "date"),
    )


# ============================================================
# Benchmarks
# ============================================================

class Benchmark(Base):
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    weights_json: Mapped[Dict[str, float]
                         ] = mapped_column(JSON, nullable=False)
    base_currency: Mapped[str] = mapped_column(String, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    snapshots: Mapped[List["BenchmarkSnapshot"]] = relationship(
        back_populates="benchmark"
    )


class BenchmarkSnapshot(Base):
    __tablename__ = "benchmark_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    benchmark_id: Mapped[int] = mapped_column(ForeignKey("benchmarks.id"))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    equity: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    benchmark: Mapped["Benchmark"] = relationship(back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint("benchmark_id", "date"),
    )


# ============================================================
# Backtest Runs
# ============================================================

class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    strategy_config_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("strategy_configs.id")
    )

    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)

    initial_equity: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    final_equity: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    total_trades: Mapped[Optional[int]] = mapped_column(Integer)
    win_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    max_drawdown: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))

    notes: Mapped[Optional[str]] = mapped_column(Text)
    data_source: Mapped[Optional[str]] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    portfolio: Mapped["Portfolio"] = relationship(
        back_populates="backtest_runs")
    strategy_config: Mapped["StrategyConfig"] = relationship(
        back_populates="backtest_runs"
    )


# ============================================================
# Candle Data (Optional)
# ============================================================

class Candle(Base):
    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    timeframe: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    open: Mapped[Optional[float]] = mapped_column(Numeric(18, 8))
    high: Mapped[Optional[float]] = mapped_column(Numeric(18, 8))
    low: Mapped[Optional[float]] = mapped_column(Numeric(18, 8))
    close: Mapped[Optional[float]] = mapped_column(Numeric(18, 8))
    volume: Mapped[Optional[float]] = mapped_column(Numeric(28, 8))

    source: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    asset: Mapped["Asset"] = relationship(back_populates="candles")

    __table_args__ = (
        UniqueConstraint("asset_id", "timeframe", "timestamp"),
    )


# ============================================================
# Signals (Optional)
# ============================================================

class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    strategy_config_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("strategy_configs.id")
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)
    signal_type: Mapped[str] = mapped_column(
        String, nullable=False)  # enter | exit | hold
    price: Mapped[Optional[float]] = mapped_column(Numeric(18, 8))
    extra: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        "metadata",  # column name
        JSON
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    portfolio: Mapped["Portfolio"] = relationship(back_populates="signals")
    strategy_config: Mapped["StrategyConfig"] = relationship(
        back_populates="signals"
    )
    asset: Mapped["Asset"] = relationship()


# ============================================================
# Risk Events
# ============================================================

class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))

    event_type: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)

    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    portfolio: Mapped["Portfolio"] = relationship(back_populates="risk_events")


# ============================================================
# Errors
# ============================================================

class ErrorLog(Base):
    __tablename__ = "errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    context: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stacktrace: Mapped[Optional[str]] = mapped_column(Text)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
