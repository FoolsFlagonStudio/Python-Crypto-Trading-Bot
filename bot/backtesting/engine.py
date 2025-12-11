# bot/backtesting/engine.py

from __future__ import annotations

from datetime import datetime, date
from typing import Sequence, Type, Any, Callable

from sqlalchemy import select

from bot.core.logger import get_logger
from bot.persistence.db import DB
from bot.persistence.models import (
    Candle,
    Portfolio,
    Trade,
    BacktestRun,
)
from bot.execution.order_manager import OrderManager
from bot.execution.base import ExecutionEngine
from bot.strategies.runner import StrategyRunner
from bot.strategies.base import Strategy
from bot.backtesting.config import BacktestConfig, BacktestResult

logger = get_logger(__name__)


class BacktestEngine:
    """
    Backtesting engine that:
      - Reuses StrategyRunner + OrderManager + ExecutionEngine
      - Runs over historical Candle rows
      - Persists a BacktestRun row + returns a BacktestResult
    """

    def __init__(
        self,
        db: DB,
        execution_engine_factory: Callable[[], ExecutionEngine],
    ) -> None:
        """
        execution_engine_factory is typically:
            lambda: SimulatedExecutionEngine(...)
        so we don't have to know its constructor signature here.
        """
        self.db = db
        self.execution_engine_factory = execution_engine_factory

    # -------------------------------------------------------------
    # Candle loader helper
    # -------------------------------------------------------------
    async def load_candles_from_db(
        self,
        asset_id: int,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """
        Pull candles from DB for a given asset/timeframe.
        """

        async with self.db.get_session() as session:
            result = await session.execute(
                select(Candle)
                .where(
                    Candle.asset_id == asset_id,
                    Candle.timeframe == timeframe,
                    Candle.timestamp >= start,
                    Candle.timestamp <= end,
                )
                .order_by(Candle.timestamp.asc())
            )
            return list(result.scalars().all())

    # -------------------------------------------------------------
    # Core backtest runner
    # -------------------------------------------------------------
    async def run_backtest(
        self,
        *,
        portfolio_id: int,
        asset_id: int,
        strategy_config_id: int,
        strategy_class: Type[Strategy],
        strategy_params: dict,
        candles: Sequence[Any],
        label: str | None = None,
        data_source: str | None = None,
        reset_portfolio_state: bool = True,
    ) -> BacktestResult:
        """
        Run a strategy over historical candles using the same live/paper
        plumbing (StrategyRunner + OrderManager + ExecutionEngine).

        candles must be an ordered sequence of objects that have:
          .timestamp (datetime)
          .close (numeric)
          .high  (optional)
          .low   (optional)
        """

        if not candles:
            raise ValueError(
                "BacktestEngine.run_backtest: no candles provided"
            )

        # Ensure chronological order
        candles = sorted(candles, key=lambda c: c.timestamp)

        start_date = candles[0].timestamp.date()
        end_date = candles[-1].timestamp.date()
        logger.info(
            "Starting backtest '%s' for portfolio=%s asset=%s from %s to %s (%d candles)",
            label or "<unnamed>",
            portfolio_id,
            asset_id,
            start_date,
            end_date,
            len(candles),
        )

        # ---------------------------------------------------------
        # Optional: reset portfolio-scoped state for clean runs
        # ---------------------------------------------------------
        if reset_portfolio_state:
            await self._reset_portfolio_state(
                portfolio_id, asset_id, strategy_config_id
            )

        # ---------------------------------------------------------
        # Load portfolio & initial equity
        # ---------------------------------------------------------
        async with self.db.get_session() as session:
            portfolio = await session.get(Portfolio, portfolio_id)
            if portfolio is None:
                raise ValueError(f"Portfolio {portfolio_id} not found")

            initial_equity = float(portfolio.starting_equity or 0.0)

        # ---------------------------------------------------------
        # Build strategy + execution pipeline
        # ---------------------------------------------------------
        strategy = strategy_class(strategy_params)
        if hasattr(strategy, "reset"):
            strategy.reset()

        execution_engine = self.execution_engine_factory()

        order_manager = OrderManager(
            db=self.db,
            execution_engine=execution_engine,
            portfolio_id=portfolio_id,
            asset_id=asset_id,
            strategy_config_id=strategy_config_id,
            strategy_params=strategy_params,
        )

        runner = StrategyRunner(
            strategy=strategy,
            db=self.db,
            portfolio_id=portfolio_id,
            asset_id=asset_id,
            strategy_config_id=strategy_config_id,
            order_manager=order_manager,
        )

        # ---------------------------------------------------------
        # Execute strategy over all candles
        # ---------------------------------------------------------
        signals = await runner.run(candles)
        logger.info("Backtest produced %d signals", len(signals))

        # ---------------------------------------------------------
        # Compute basic trade statistics
        # ---------------------------------------------------------
        async with self.db.get_session() as session:
            trades_result = await session.execute(
                select(Trade).where(
                    Trade.portfolio_id == portfolio_id,
                    Trade.asset_id == asset_id,
                    Trade.strategy_config_id == strategy_config_id,
                )
            )
            trades = list(trades_result.scalars().all())

            closed_trades = [t for t in trades if t.realized_pnl is not None]

            total_trades = len(closed_trades)
            winning_trades = sum(
                1
                for t in closed_trades
                if t.realized_pnl is not None and t.realized_pnl > 0
            )
            # (losing_trades is available if you want it)
            realized_pnl = float(
                sum((t.realized_pnl or 0) for t in closed_trades)
            )
            win_rate = (winning_trades / total_trades) if total_trades else 0.0

            final_equity = initial_equity + realized_pnl

            # -----------------------------------------------------
            # Persist BacktestRun (analytics enhanced in Part 11)
            # -----------------------------------------------------
            backtest_run = BacktestRun(
                portfolio_id=portfolio_id,
                strategy_config_id=strategy_config_id,
                start_date=start_date,
                end_date=end_date,
                initial_equity=initial_equity,
                final_equity=final_equity,
                total_trades=total_trades,
                win_rate=win_rate * 100.0,  # store as %
                max_drawdown=None,          # to be computed later
                notes=label,
                data_source=data_source,
            )
            session.add(backtest_run)
            await session.commit()
            await session.refresh(backtest_run)

        logger.info(
            "Backtest '%s' complete: equity %.2f → %.2f | trades=%d | win_rate=%.1f%%",
            label or "<unnamed>",
            initial_equity,
            final_equity,
            total_trades,
            win_rate * 100.0,
        )

        # For now, max_drawdown is a placeholder (0.0).
        # We'll recompute properly in Part 11 from equity curve.
        return BacktestResult(
            backtest_run_id=backtest_run.id,
            portfolio_id=portfolio_id,
            asset_id=asset_id,
            strategy_config_id=strategy_config_id,
            start_equity=initial_equity,
            final_equity=final_equity,
            total_trades=total_trades,
            win_rate=win_rate,
            max_drawdown=0.0,
            signals_count=len(signals),
        )

    # -------------------------------------------------------------
    # Internal: resetting state for a clean portfolio backtest
    # -------------------------------------------------------------
    async def _reset_portfolio_state(
        self,
        portfolio_id: int,
        asset_id: int,
        strategy_config_id: int,
    ) -> None:
        """
        Wipes portfolio-scoped ephemeral state for a fresh backtest.

        IMPORTANT: Only safe if you use dedicated 'backtest' portfolios.
        Do NOT point this at your live/paper portfolio.
        """
        from bot.persistence.models import (
            Order,
            Signal,
            RiskEvent,
            DailySnapshot,
        )

        async with self.db.get_session() as session:
            # Orders
            await session.execute(
                Order.__table__.delete().where(
                    Order.portfolio_id == portfolio_id,
                    Order.asset_id == asset_id,
                    Order.strategy_config_id == strategy_config_id,
                )
            )
            # Trades
            await session.execute(
                Trade.__table__.delete().where(
                    Trade.portfolio_id == portfolio_id,
                    Trade.asset_id == asset_id,
                    Trade.strategy_config_id == strategy_config_id,
                )
            )
            # Signals
            await session.execute(
                Signal.__table__.delete().where(
                    Signal.portfolio_id == portfolio_id,
                    Signal.asset_id == asset_id,
                    Signal.strategy_config_id == strategy_config_id,
                )
            )
            # Risk events
            await session.execute(
                RiskEvent.__table__.delete().where(
                    RiskEvent.portfolio_id == portfolio_id,
                )
            )
            # Daily snapshots
            await session.execute(
                DailySnapshot.__table__.delete().where(
                    DailySnapshot.portfolio_id == portfolio_id,
                )
            )

            await session.commit()
            logger.info(
                "Reset state for portfolio=%s asset=%s strategy_config=%s",
                portfolio_id,
                asset_id,
                strategy_config_id,
            )


# -------------------------------------------------------------
# Convenience free function: run_backtest(db, cfg)
# -------------------------------------------------------------
from bot.execution.simulated import SimulatedExecutionEngine  # noqa: E402


async def run_backtest(
    db: DB,
    cfg: BacktestConfig,
) -> BacktestResult:
    """
    Convenience wrapper so scripts can just call:
        result = await run_backtest(db, cfg)

    Uses:
      - SimulatedExecutionEngine for execution
      - Historical candles from the candles table
    """

    engine = BacktestEngine(
        db=db,
        execution_engine_factory=lambda: SimulatedExecutionEngine(),
    )

    candles = await engine.load_candles_from_db(
        asset_id=cfg.asset_id,
        timeframe=cfg.timeframe,
        start=cfg.start,
        end=cfg.end,
    )

    if not candles:
        raise RuntimeError(
            f"No candles found for asset_id={cfg.asset_id}, "
            f"timeframe={cfg.timeframe}, start={cfg.start}, end={cfg.end}"
        )

    return await engine.run_backtest(
        portfolio_id=cfg.portfolio_id,
        asset_id=cfg.asset_id,
        strategy_config_id=cfg.strategy_config_id,
        strategy_class=cfg.strategy_class,
        strategy_params=cfg.strategy_params,
        candles=candles,
        label=cfg.label,
        data_source=cfg.data_source,
        reset_portfolio_state=True,
    )
