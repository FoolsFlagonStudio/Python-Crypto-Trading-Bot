from bot.strategies.base import Strategy


class GreenCandleStrategy(Strategy):
    """
    Very simple demonstration strategy:
        - Enter when close > open (green candle)
        - Exit when close < open (red candle)
    """

    def should_enter(self, candle, portfolio_state):
        return candle.close > candle.open

    def should_exit(self, candle, portfolio_state):
        return candle.close < candle.open
