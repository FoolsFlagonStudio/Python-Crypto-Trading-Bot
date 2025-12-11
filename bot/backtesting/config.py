# bot/backtesting/config.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Type


@dataclass
class BacktestConfig:
    """
    Configuration for a single backtest run.
    """

    # Core linking
    portfolio_id: int
    asset_id: int
    strategy_config_id: int

    # Strategy
    strategy_class: Type[Any]          # e.g. MeanReversionStrategy
    strategy_params: dict[str, Any]

    # Market data
    timeframe: str                     # e.g. "ONE_MINUTE"
    start: datetime
    end: datetime

    # Execution assumptions (for sim engines)
    fee_bps: float = 1.0               # 1.0 = 1 basis point (0.01%)
    slippage_bps: float = 0.0          # per-trade slippage assumption

    # Metadata
    label: str | None = None
    data_source: str = "candles_table"
    notes: str | None = None


@dataclass
class BacktestResult:
    """
    Summary of a completed backtest.
    BacktestRun row is persisted to DB; this is the in-memory summary.
    """
    backtest_run_id: int
    portfolio_id: int
    asset_id: int
    strategy_config_id: int

    start_equity: float
    final_equity: float
    total_trades: int
    win_rate: float        # 0–1
    max_drawdown: float    # 0–1 (placeholder for now)
    signals_count: int
