from bot.risk.result import RiskCheckResult


class RiskManager:
    def __init__(self, db, portfolio_id, asset_id, strategy_params):
        self.db = db
        self.portfolio_id = portfolio_id
        self.asset_id = asset_id
        self.strategy_params = strategy_params

        # Pull defaults from strategy params (overrideable)
        self.max_risk_per_trade_pct = strategy_params.get("max_risk_pct", 0.02)
        self.max_daily_loss_pct = strategy_params.get(
            "max_daily_loss_pct", 0.03)
        self.max_trades_per_day = strategy_params.get("max_trades_per_day", 6)

    async def evaluate_entry(self, candle, state) -> RiskCheckResult:
        portfolio = state.portfolio
        if portfolio is None:
            return RiskCheckResult(
                allow=False,
                size=None,
                warnings=[],
                veto_reason=f"Portfolio {self.portfolio_id} not found.",
            )

        warnings = []

        portfolio = state.portfolio

        # Get equity
        equity = (
            state.last_snapshot.ending_equity
            if state.last_snapshot
            else portfolio.starting_equity
        )

        if equity is None:
            return RiskCheckResult(
                allow=False,
                size=None,
                warnings=[],
                veto_reason="No equity data available."
            )

        # Calculate recommended size
        price = candle.close
        max_risk_dollars = equity * self.max_risk_per_trade_pct
        size = max_risk_dollars / price

        # =====================================================================
        # HARD RULES (VETO)
        # =====================================================================

        # Daily loss limit
        if state.last_snapshot and state.last_snapshot.realized_pnl is not None:
            pnl_today = float(state.last_snapshot.realized_pnl)
            if pnl_today < -equity * self.max_daily_loss_pct:
                return RiskCheckResult(
                    allow=False,
                    size=None,
                    warnings=[],
                    veto_reason=f"Daily loss exceeded: {pnl_today:.2f}"
                )

        # Trades-per-day limit
        if len(state.open_trades) >= self.max_trades_per_day:
            return RiskCheckResult(
                allow=False,
                size=None,
                warnings=[],
                veto_reason=f"Max trades per day ({self.max_trades_per_day}) reached."
            )

        # =====================================================================
        # SOFT RULES (WARNINGS)
        # =====================================================================

        # Example volatility warning (not a veto)
        if candle.high - candle.low > candle.close * 0.02:
            warnings.append("High intraday volatility detected.")

        return RiskCheckResult(
            allow=True,
            size=size,
            warnings=warnings,
            veto_reason=None
        )
