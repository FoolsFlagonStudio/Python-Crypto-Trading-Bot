from dataclasses import dataclass
from typing import Optional, Dict, Any, List


@dataclass
class RiskCheckResult:
    allow: bool            # If False → veto
    size: Optional[float]  # Recommended size (from risk module)
    warnings: List[str]    # Soft warnings (print but continue)
    veto_reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def is_veto(self) -> bool:
        return not self.allow
