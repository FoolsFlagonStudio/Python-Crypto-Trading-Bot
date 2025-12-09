from __future__ import annotations

from bot.execution.live_coinbase import LiveCoinbaseExecutionEngine
from bot.execution.simulated import SimulatedExecutionEngine
from bot.execution.base import ExecutionEngine


def build_execution_engine(
    mode: str,
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> ExecutionEngine:
    """
    mode: 'live' | 'paper'
    """
    mode = mode.lower()

    if mode == "live":
        if not api_key or not api_secret:
            raise ValueError("Live mode requires api_key and api_secret.")
        return LiveCoinbaseExecutionEngine(api_key=api_key, api_secret=api_secret)

    if mode == "paper":
        # no keys needed, pure simulation
        return SimulatedExecutionEngine()

    raise ValueError(f"Unknown trading mode: {mode}")
