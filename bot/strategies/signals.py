from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


class SignalType:
    ENTER = "enter"
    EXIT = "exit"
    HOLD = "hold"


@dataclass
class StrategySignal:
    timestamp: datetime
    signal_type: str               # enter | exit | hold
    price: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
