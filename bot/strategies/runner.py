from bot.core.logger import get_logger
from bot.persistence.db import DB
from bot.execution.order_manager import OrderManager
from bot.strategies.signals import SignalType

logger = get_logger(__name__)


class StrategyRunner:
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

        # optional — can be None in backtests
        self.order_manager = order_manager

        # prevent two ENTER in a row, etc.
        self.last_signal_type = None

    async def run(self, candles):
        """
        Main loop for executing a strategy over a series of candles.
        Returns a list of StrategySignal objects.
        """
        signals = []

        for candle in candles:

            # load latest portfolio snapshot / open orders / open trades
            portfolio_state = await self.db.load_portfolio_state(self.portfolio_id)

            # let the strategy compute the next signal
            sig = self.strategy.generate_signal(candle, portfolio_state)

            if sig is None:
                continue

            # prevent spam signals (enter-enter-enter)
            if sig.signal_type == self.last_signal_type:
                logger.debug(f"Skipping duplicate {sig.signal_type} signal")
                continue

            self.last_signal_type = sig.signal_type
            signals.append(sig)

            logger.info(f"[SIGNAL] {sig.signal_type.upper()} @ {sig.price}")

            # write signal record
            await self.db.record_signal(
                portfolio_id=self.portfolio_id,
                asset_id=self.asset_id,
                strategy_config_id=self.strategy_config_id,
                signal_type=sig.signal_type,
                price=sig.price,
                extra=sig.metadata,
                timestamp=sig.timestamp,
            )

            # -----------------------------------------
            # EXECUTION SECTION
            # -----------------------------------------
            if self.order_manager:
                if sig.signal_type == SignalType.ENTER:
                    await self.order_manager.handle_enter(sig.price, sig.timestamp)

                elif sig.signal_type == SignalType.EXIT:
                    await self.order_manager.handle_exit(sig.price, sig.timestamp)

                # HOLD does nothing

        return signals
