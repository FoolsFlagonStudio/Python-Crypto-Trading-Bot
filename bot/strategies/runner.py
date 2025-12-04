from bot.core.logger import get_logger
from bot.persistence.db import DB

logger = get_logger(__name__)


class StrategyRunner:
    def __init__(self, strategy, db: DB, portfolio_id: int, asset_id: int, strategy_config_id: int):
        self.strategy = strategy
        self.db = db
        self.portfolio_id = portfolio_id
        self.asset_id = asset_id
        self.strategy_config_id = strategy_config_id

        # Prevent duplicate signals in a row
        self.last_signal_type = None

    async def run(self, candles):
        signals = []

        for candle in candles:
            # Load state on each step (live trading would optimize this)
            portfolio_state = await self.db.load_portfolio_state(self.portfolio_id)

            sig = self.strategy.generate_signal(candle, portfolio_state)

            if sig is None:
                continue

            # Avoid enter-enter or exit-exit spam
            if sig.signal_type == self.last_signal_type:
                logger.debug(f"Skipping duplicate {sig.signal_type} signal")
                continue

            self.last_signal_type = sig.signal_type
            signals.append(sig)

            logger.info(f"Recording {sig.signal_type.upper()} @ {sig.price}")

            # Save to DB
            await self.db.record_signal(
                portfolio_id=self.portfolio_id,
                asset_id=self.asset_id,
                strategy_config_id=self.strategy_config_id,
                signal_type=sig.signal_type,
                price=sig.price,
                extra=sig.metadata,
                timestamp=sig.timestamp,
            )

        return signals
