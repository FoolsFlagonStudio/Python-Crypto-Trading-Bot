from datetime import datetime, timezone
from typing import Optional

from bot.core.logger import get_logger
from bot.strategies.signals import StrategySignal, SignalType

logger = get_logger(__name__)


class Strategy:
    """
    Base interface for all strategies.
    Strategies must define:
        - should_enter(candle, portfolio_state)
        - should_exit(candle, portfolio_state)

    HOLD is automatically produced when neither rule triggers.
    """

    def __init__(self, params: dict | None = None):
        self.params = params or {}

    # ------------------------------------------------------------------
    # Rules every strategy must implement
    # ------------------------------------------------------------------

    def should_enter(self, candle, portfolio_state) -> bool:
        raise NotImplementedError

    def should_exit(self, candle, portfolio_state) -> bool:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Generate a StrategySignal (ENTER / EXIT / HOLD)
    # ------------------------------------------------------------------

    def generate_signal(self, candle, portfolio_state) -> StrategySignal:
        """Evaluate entry/exit logic and return a StrategySignal."""

        ts = datetime.now(timezone.utc)
        price = candle.close

        # ---- ENTER ----
        if self.should_enter(candle, portfolio_state):
            meta = {"reason": "enter_rule_triggered"}
            logger.info(f"[SIGNAL] ENTER @ {price}")
            return StrategySignal(
                timestamp=ts,
                signal_type=SignalType.ENTER,
                price=price,
                metadata=meta,
            )

        # ---- EXIT ----
        if self.should_exit(candle, portfolio_state):
            meta = {"reason": "exit_rule_triggered"}
            logger.info(f"[SIGNAL] EXIT @ {price}")
            return StrategySignal(
                timestamp=ts,
                signal_type=SignalType.EXIT,
                price=price,
                metadata=meta,
            )

        # ---- HOLD (default) ----
        meta = {"reason": "hold_default"}
        logger.debug(f"[SIGNAL] HOLD @ {price}")
        return StrategySignal(
            timestamp=ts,
            signal_type=SignalType.HOLD,
            price=price,
            metadata=meta,
        )
