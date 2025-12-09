from __future__ import annotations

import os
from dotenv import load_dotenv
from dataclasses import dataclass


# Load .env file from project root
load_dotenv()


@dataclass
class BotConfig:
    mode: str  # "live" or "paper"
    api_key: str | None
    api_secret: str | None

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def is_paper(self) -> bool:
        return self.mode == "paper"


def load_bot_config() -> BotConfig:
    mode = os.getenv("TRADING_MODE", "paper").lower()

    if mode not in ("live", "paper"):
        raise ValueError(f"Invalid TRADING_MODE: {mode}")

    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")

    if mode == "live" and (not api_key or not api_secret):
        raise ValueError(
            "Live mode requires COINBASE_API_KEY and COINBASE_API_SECRET in .env"
        )

    return BotConfig(
        mode=mode,
        api_key=api_key,
        api_secret=api_secret,
    )
