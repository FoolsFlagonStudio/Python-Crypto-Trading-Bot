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

    async def run(self, candles: Iterable) -> List[StrategySignal]:
        """
        Main loop for executing a strategy over a series of candles.

        Returns:
            List[StrategySignal]  - all signals produced (enter/exit/hold)
        """
        signals: list[StrategySignal] = []

        for candle in candles:
            # -------------------------------------------------
            # Load current portfolio state ONCE per candle
            # (open trades, open orders, last snapshot, etc.)
            # -------------------------------------------------
            portfolio_state: PortfolioState = await self.db.load_portfolio_state(
                self.portfolio_id
            )

            # -------------------------------------------------
            # Per-candle trade tracking & auto exits
            # -------------------------------------------------
            if self.order_manager:
                # These now accept the current state so we don't reload in each.
                await self.order_manager.update_trade_tracking_each_candle(
                    candle, portfolio_state
                )
                await self.order_manager.check_auto_exits(
                    candle, portfolio_state
                )

            # -------------------------------------------------
            # Strategy produces the next signal from this candle + state
            # -------------------------------------------------
            sig = self.strategy.generate_signal(candle, portfolio_state)

            if sig is None:
                continue

            # Debounce: avoid ENTER→ENTER→ENTER or EXIT→EXIT→EXIT spam
            if sig.signal_type == self.last_signal_type:
                logger.debug(
                    f"[STRATEGY] Skipping duplicate {sig.signal_type} signal")
                continue

            self.last_signal_type = sig.signal_type
            signals.append(sig)

            logger.info(
                f"[SIGNAL] {sig.signal_type.value.upper()} @ {sig.price}")

            # -------------------------------------------------
            # Persist the signal itself
            # -------------------------------------------------
            await self.db.record_signal(
                portfolio_id=self.portfolio_id,
                asset_id=self.asset_id,
                strategy_config_id=self.strategy_config_id,
                signal_type=sig.signal_type.value,
                price=sig.price,
                extra=sig.metadata,
                timestamp=sig.timestamp,
            )

            # -------------------------------------------------
            # EXECUTION SECTION (optional)
            # -------------------------------------------------
            if not self.order_manager:
                # pure backtest mode — caller can interpret signals manually
                continue

            # -------------------------------
            # ENTER logic + risk checks
            # -------------------------------
            if sig.signal_type == SignalType.ENTER:
                # Primary risk check
                risk = await self.order_manager.risk_manager.evaluate_entry(
                    candle=candle,
                    state=portfolio_state,
                )

                if risk.is_veto():
                    logger.warning(f"[RISK VETO] {risk.veto_reason}")
                    await self._record_risk_veto(
                        veto_reason=risk.veto_reason or "unspecified",
                        candle=candle,
                        signal_price=sig.price,
                    )
                    continue

                # Soft warnings (no veto)
                for w in risk.warnings:
                    logger.warning(f"[RISK WARNING] {w}")
                    await self._record_risk_warning(
                        warning=w,
                        candle=candle,
                        signal_price=sig.price,
                    )

                # Hand off to OrderManager; risk size wins
                await self.order_manager.handle_enter(
                    price=sig.price,
                    timestamp=sig.timestamp,
                    candle=candle,
                    size_override=risk.size,
                    state=portfolio_state,
                )

            # -------------------------------
            # EXIT logic
            # -------------------------------
            elif sig.signal_type == SignalType.EXIT:
                await self.order_manager.handle_exit(
                    price=sig.price,
                    timestamp=sig.timestamp,
                    state=portfolio_state,
                )

            # HOLD does nothing

        return signals
