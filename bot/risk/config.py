from dataclasses import dataclass

@dataclass
class DefaultRiskConfig:
    # Core risk limits
    max_risk_per_trade_pct: float = 2.0        # % of equity
    max_daily_loss_pct: float = 3.0            # halt if >= -3% equity
    max_drawdown_pct: float = 15.0             # global kill-switch

    # Activity caps
    max_trades_per_day: int = 6                # entry events per day
    max_open_trades: int = 6                   # simultaneous open trades

    # Volatility filter (soft rule)
    volatility_filter_enabled: bool = False
    max_volatility_pct: float = 4.0            # ATR-like % threshold

    # Circuit breakers
    halt_on_risk_violation: bool = True
    halt_on_connection_errors: bool = True


def load_default_risk_config() -> DefaultRiskConfig:
    """Return the default risk config."""
    return DefaultRiskConfig()
