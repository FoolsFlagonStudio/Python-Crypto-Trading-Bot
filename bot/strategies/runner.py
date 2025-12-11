from __future__ import annotations

from typing import Iterable, List

from bot.core.logger import get_logger
from bot.persistence.db import DB, PortfolioState
from bot.execution.order_manager import OrderManager
from bot.strategies.signals import SignalType, StrategySignal

logger = get_logger(__name__)


class StrategyRunner:
    """
    Orchestrates:
      - loading portfolio state per candle
      - calling the strategy to generate signals
      - running risk checks
      - invoking the OrderManager for ENTER/EXIT
      - recording signals (and risk events)
    """

    def __init__(
        self,
        strategy,
        db: DB,
        portfolio_id: int,
        asset_id: int,
        strategy_config_id: int,
        order_manager: OrderManager | None = None,
    ):
        self.strategy = strategy
        self.db = db
        self.portfolio_id = portfolio_id
        self.asset_id = asset_id
        self.strategy_config_id = strategy_config_id

        # optional — can be None in pure backtests
        self.order_manager = order_manager

        # prevent two ENTER or two EXIT in a row from the strategy
        self.last_signal_type: SignalType | None = None

        self.logger = logger

    async def _record_risk_veto(
        self,
        veto_reason: str,
        candle,
        signal_price: float,
    ) -> None:
        """
        Persist a RiskEvent for a hard veto (no trade taken).
        """
        try:
            await self.db.record_risk_event(
                portfolio_id=self.portfolio_id,
                event_type="EntryVeto",
                details={
                    "reason": veto_reason,
                    "candle_timestamp": getattr(candle, "timestamp", None),
                    "candle_close": getattr(candle, "close", None),
                    "signal_price": float(signal_price),
                },
                triggered_at=getattr(candle, "timestamp", None),
            )
        except Exception:
            # Risk logging should never crash trading loop.
            logger.exception("[RISK] Failed to record veto RiskEvent")

    async def _record_risk_warning(
        self,
        warning: str,
        candle,
        signal_price: float,
    ) -> None:
        """
        Persist a RiskEvent for a soft warning (trade still allowed).
        """
        try:
            await self.db.record_risk_event(
                portfolio_id=self.portfolio_id,
                event_type="RiskWarning",
                details={
                    "warning": warning,
                    "candle_timestamp": getattr(candle, "timestamp", None),
                    "candle_close": getattr(candle, "close", None),
                    "signal_price": float(signal_price),
                },
                triggered_at=getattr(candle, "timestamp", None),
            )
        except Exception:
            logger.exception("[RISK] Failed to record warning RiskEvent")

    async def run(self, candles):
        """
        Run strategy over a chronological list of candle-like objects.
        Produces a list of StrategySignal objects and triggers the order manager.
        """
        signals = []

        for candle in candles:
            timestamp = candle.timestamp
            price = float(candle.close)

            # Get the signal from the strategy
            sig = self.strategy.on_bar(candle)

            # Normalize missing or None signals → HOLD
            if sig is None:
                continue

            # ----------------------------
            # Normalize signal_type safely
            # ----------------------------
            raw_type = sig.signal_type

            if raw_type is None:
                continue  # treat as HOLD / skip

            # Enum → extract value
            if hasattr(raw_type, "value"):
                signal_type = str(raw_type.value)

            # Already a string
            elif isinstance(raw_type, str):
                signal_type = raw_type

            # Numeric / weird values: treat as HOLD (or raise, your choice)
            else:
                self.logger.debug(f"[WARN] Invalid signal_type {raw_type}; treating as HOLD")
                signal_type = "HOLD"

            # debug logging
            self.logger.debug(f"[SIGNAL] {signal_type.upper()} @ {sig.price}")

            # Record signal into DB (async safe)
            await self.db.record_signal(
                portfolio_id=self.portfolio_id,
                asset_id=self.asset_id,
                strategy_config_id=self.strategy_config_id,
                signal_type=signal_type,
                price=sig.price,
                extra=sig.metadata,
                timestamp=timestamp,
            )

            # Pass into order manager
            await self.order_manager.handle_signal(
                signal_type=signal_type,
                price=sig.price,
                timestamp=timestamp,
            )

            signals.append(sig)

        return signals
