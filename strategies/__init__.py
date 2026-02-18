"""
ALPHARAGHU - Strategy Combiner
Aggregates all 3 strategies into one consensus signal.
Works with both normal imports and importlib direct loading.
"""
import sys
import logging

logger = logging.getLogger("alpharaghu.strategies")


class StrategyCombiner:
    """
    Runs all 3 strategies and combines into a final signal.
    A trade is only triggered if at least 2/3 strategies agree.
    """

    def __init__(self):
        # Load strategies — works whether loaded via importlib or normal import
        if "strategy1" in sys.modules:
            # Loaded via importlib (main.py approach)
            self.strat1 = sys.modules["strategy1"].MomentumStrategy()
            self.strat2 = sys.modules["strategy2"].MeanReversionStrategy()
            self.strat3 = sys.modules["strategy3"].NewsSentimentStrategy()
        else:
            # Fallback: normal package import
            from strategies.strategy1_momentum       import MomentumStrategy
            from strategies.strategy2_mean_reversion import MeanReversionStrategy
            from strategies.strategy3_news_sentiment import NewsSentimentStrategy
            self.strat1 = MomentumStrategy()
            self.strat2 = MeanReversionStrategy()
            self.strat3 = NewsSentimentStrategy()

        import config
        self.weights = config.STRATEGY_WEIGHTS

    def run(self, symbol: str, df_15min, df_daily, news_articles: list = None) -> dict:
        results = {}

        # ── Run each strategy ────────────────────────────────
        for name, strat, extra_kwargs in [
            ("momentum",       self.strat1, {}),
            ("mean_reversion", self.strat2, {}),
            ("news_sentiment", self.strat3, {"symbol": symbol, "news_articles": news_articles}),
        ]:
            try:
                if name == "news_sentiment":
                    results[name] = strat.generate_signal(df_15min, **extra_kwargs)
                else:
                    results[name] = strat.generate_signal(df_15min)
            except Exception as e:
                logger.error(f"{name} error for {symbol}: {e}")
                results[name] = {"signal": "HOLD", "strength": 0.0, "reason": str(e), "indicators": {}}

        # ── Consensus Scoring ────────────────────────────────
        buy_weight  = 0.0
        sell_weight = 0.0

        for name, result in results.items():
            w        = self.weights.get(name, 0.33)
            sig      = result.get("signal", "HOLD")
            strength = result.get("strength", 0.0)
            if sig == "BUY":
                buy_weight  += w * strength
            elif sig == "SELL":
                sell_weight += w * strength

        buy_consensus  = sum(1 for r in results.values() if r.get("signal") == "BUY")
        sell_consensus = sum(1 for r in results.values() if r.get("signal") == "SELL")

        max_weight = sum(self.weights.values())
        buy_conf   = buy_weight  / max_weight
        sell_conf  = sell_weight / max_weight

        final_signal = "HOLD"
        confidence   = 0.0
        consensus    = 0

        if buy_consensus >= 2 or (buy_consensus == 1 and buy_conf >= 0.55):
            final_signal = "BUY"
            confidence   = round(buy_conf, 2)
            consensus    = buy_consensus
        elif sell_consensus >= 2 or (sell_consensus == 1 and sell_conf >= 0.55):
            final_signal = "SELL"
            confidence   = round(sell_conf, 2)
            consensus    = sell_consensus

        strategy_lines = []
        for name, result in results.items():
            emoji = {"BUY": "GREEN", "SELL": "RED", "HOLD": "HOLD"}.get(result.get("signal"), "HOLD")
            strategy_lines.append(
                f"[{emoji}] {name.replace('_',' ').title()}: "
                f"{result.get('signal','HOLD')} ({result.get('strength', 0):.0%}) — "
                f"{result.get('reason', '')}"
            )

        return {
            "symbol":           symbol,
            "signal":           final_signal,
            "confidence":       confidence,
            "consensus":        consensus,
            "strategy_signals": results,
            "reason_lines":     strategy_lines,
            "buy_confidence":   round(buy_conf, 2),
            "sell_confidence":  round(sell_conf, 2),
        }
