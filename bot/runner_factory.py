from bot.config import load_bot_config
from bot.execution.factory import build_execution_engine
from bot.execution.order_manager import OrderManager
from bot.strategies.runner import StrategyRunner
from bot.persistence.db import DB


async def build_runner(
    portfolio_id: int,
    asset_id: int,
    strategy_config_id: int,
    strategy_params: dict,
    strategy_class,
):
    config = load_bot_config()
    db = DB()

    execution_engine = build_execution_engine(
        mode=config.mode,
        api_key=config.api_key,
        api_secret=config.api_secret,
    )

    order_manager = OrderManager(
        db=db,
        execution_engine=execution_engine,
        portfolio_id=portfolio_id,
        asset_id=asset_id,
        strategy_config_id=strategy_config_id,
        strategy_params=strategy_params,
    )

    strategy = strategy_class(params=strategy_params)

    runner = StrategyRunner(
        strategy=strategy,
        db=db,
        portfolio_id=portfolio_id,
        asset_id=asset_id,
        strategy_config_id=strategy_config_id,
        order_manager=order_manager,
    )

    return runner
