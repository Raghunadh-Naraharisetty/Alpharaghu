"""
ALPHARAGHU - Strategy 3: News Sentiment + Earnings Catalyst
=============================================================
LOGIC:
  BUY  when: Positive news sentiment score > threshold,
             OR Earnings beat + positive reaction,
             AND Technical momentum confirms (price + volume spike)

  SELL when: Negative sentiment score,
             OR Earnings miss,
             OR Fade the news (price already up > 3% on news)

DATA SOURCES:
  1. Alpaca built-in News API  (real-time, no extra key needed)
  2. NewsAPI.org               (free tier: 100 requests/day)
  3. yfinance                  (earnings calendar, quarterly results)

SENTIMENT ENGINE:
  Uses VADER (NLTK) for fast rule-based sentiment analysis
  + keyword scoring for finance-specific terms
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

logger = logging.getLogger("alpharaghu.strategy.news_sentiment")

# Finance-specific sentiment words
BULLISH_WORDS = {
    "beat": 3, "beats": 3, "record": 2, "record high": 3,
    "raised guidance": 3, "upgrade": 2, "buy rating": 2,
    "strong earnings": 3, "revenue growth": 2, "profit surge": 3,
    "acquisition": 1, "buyback": 2, "dividend increase": 2,
    "positive": 1, "growth": 1, "bullish": 2, "outperform": 2,
    "breakthrough": 2, "approval": 2, "fda approved": 3,
    "partnership": 1, "deal": 1, "contract": 1,
}
BEARISH_WORDS = {
    "miss": 3, "misses": 3, "below expectations": 3,
    "lowered guidance": 3, "downgrade": 2, "sell rating": 2,
    "revenue decline": 2, "profit drop": 3, "layoffs": 2,
    "investigation": 2, "lawsuit": 2, "recall": 2,
    "negative": 1, "bearish": 2, "underperform": 2,
    "loss": 2, "debt": 1, "bankruptcy": 3, "default": 3,
    "warning": 2, "cut": 1, "miss": 3,
}


def score_text(text: str) -> float:
    """Score a text string. Returns -1.0 to +1.0"""
    if not text:
        return 0.0
    text_lower = text.lower()
    score = 0
    max_score = 0

    for word, weight in BULLISH_WORDS.items():
        if word in text_lower:
            score += weight
            max_score += weight

    for word, weight in BEARISH_WORDS.items():
        if word in text_lower:
            score -= weight
            max_score += weight

    if max_score == 0:
        return 0.0
    return max(min(score / max_score, 1.0), -1.0)


class NewsSentimentStrategy:
    name = "news_sentiment"
    display_name = "📰 News Sentiment + Earnings"

    def __init__(self,
                 sentiment_threshold: float = 0.3,
                 min_articles: int = 2,
                 news_hours_lookback: int = 24):
        self.sentiment_threshold  = sentiment_threshold
        self.min_articles         = min_articles
        self.news_hours_lookback  = news_hours_lookback
        self._news_cache: dict    = {}   # symbol → {timestamp, articles, score}

    # ── Sentiment Scoring ────────────────────────────────────
    def score_articles(self, articles: list) -> dict:
        """Score a list of news articles"""
        if not articles:
            return {"score": 0.0, "count": 0, "articles": []}

        scored = []
        for art in articles:
            headline = art.get("headline", "")
            summary  = art.get("summary", "")
            combined = f"{headline} {summary}"
            s = score_text(combined)
            scored.append({
                "headline":   headline,
                "score":      s,
                "source":     art.get("source", ""),
                "created_at": art.get("created_at", ""),
            })

        avg_score = sum(a["score"] for a in scored) / len(scored)
        return {
            "score":    round(avg_score, 3),
            "count":    len(scored),
            "articles": scored,
            "top_headline": scored[0]["headline"] if scored else "",
        }

    # ── Earnings Check ───────────────────────────────────────
    def check_earnings(self, symbol: str) -> dict:
        """Check recent earnings via yfinance"""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info   = ticker.info

            eps_actual   = info.get("trailingEps", None)
            pe_ratio     = info.get("trailingPE", None)
            revenue_growth = info.get("revenueGrowth", None)
            earnings_growth = info.get("earningsGrowth", None)

            # Earnings calendar
            calendar = ticker.calendar
            next_earnings = None
            if calendar is not None and not calendar.empty:
                try:
                    next_earnings = str(calendar.iloc[0, 0])
                except Exception:
                    pass

            catalyst_score = 0.0
            if revenue_growth and revenue_growth > 0.1:
                catalyst_score += 0.3
            if earnings_growth and earnings_growth > 0.1:
                catalyst_score += 0.3
            if pe_ratio and pe_ratio < 25:
                catalyst_score += 0.2

            return {
                "eps":              eps_actual,
                "pe_ratio":         pe_ratio,
                "revenue_growth":   revenue_growth,
                "earnings_growth":  earnings_growth,
                "next_earnings":    next_earnings,
                "catalyst_score":   round(catalyst_score, 2),
            }
        except Exception as e:
            logger.debug(f"Earnings check failed for {symbol}: {e}")
            return {"catalyst_score": 0.0}

    # ── Price Reaction to News ───────────────────────────────
    def get_price_reaction(self, df: pd.DataFrame) -> dict:
        """Check if price is reacting to news with volume"""
        if len(df) < 5:
            return {"reaction": "neutral", "pct_change": 0.0}

        recent_change = (df["close"].iloc[-1] - df["close"].iloc[-4]) / df["close"].iloc[-4] * 100
        avg_vol  = df["volume"].rolling(20).mean().iloc[-1]
        vol_now  = df["volume"].iloc[-1]
        vol_ratio = vol_now / avg_vol if avg_vol else 1

        if recent_change > 1.5 and vol_ratio > 1.5:
            reaction = "strong_positive"
        elif recent_change > 0.5:
            reaction = "mild_positive"
        elif recent_change < -1.5 and vol_ratio > 1.5:
            reaction = "strong_negative"
        elif recent_change < -0.5:
            reaction = "mild_negative"
        else:
            reaction = "neutral"

        return {
            "reaction":   reaction,
            "pct_change": round(recent_change, 2),
            "vol_ratio":  round(vol_ratio, 2),
        }

    # ── Signal Generation ────────────────────────────────────
    def generate_signal(self, df: pd.DataFrame, symbol: str,
                        news_articles: list = None) -> dict:
        if not news_articles:
            return self._no_signal("No recent news data")

        sentiment = self.score_articles(news_articles)
        earnings  = self.check_earnings(symbol)
        price_rx  = self.get_price_reaction(df)

        score     = sentiment["score"]
        n_arts    = sentiment["count"]
        e_score   = earnings.get("catalyst_score", 0.0)
        combined  = score * 0.6 + e_score * 0.4

        indicators = {
            "sentiment_score":  score,
            "article_count":    n_arts,
            "earnings_catalyst": e_score,
            "combined_score":   round(combined, 3),
            "price_reaction":   price_rx["reaction"],
            "pct_change":       price_rx["pct_change"],
            "top_headline":     sentiment.get("top_headline", "")[:80],
        }

        # ── BUY Signal ────────────────────────────────────────
        strong_positive_news = score >= self.sentiment_threshold and n_arts >= self.min_articles
        earnings_catalyst    = e_score >= 0.3
        price_confirms_buy   = price_rx["reaction"] in ("strong_positive", "mild_positive")
        # Don't buy if price already ran > 3% (too late, risk fades)
        not_too_late         = price_rx["pct_change"] < 3.0

        buy_score = sum([
            strong_positive_news * 3.0,
            earnings_catalyst    * 2.0,
            price_confirms_buy   * 1.5,
            not_too_late         * 1.0,
        ])
        buy_max = 7.5

        # ── SELL Signal ───────────────────────────────────────
        strong_negative_news = score <= -self.sentiment_threshold and n_arts >= self.min_articles
        price_confirms_sell  = price_rx["reaction"] in ("strong_negative", "mild_negative")
        fade_the_news        = price_rx["pct_change"] >= 3.0 and score > 0  # Buy the rumor, sell the news

        sell_score = sum([
            strong_negative_news * 3.0,
            price_confirms_sell  * 1.5,
            fade_the_news        * 2.0,
        ])
        sell_max = 6.5

        buy_strength  = buy_score  / buy_max
        sell_strength = sell_score / sell_max

        if buy_strength >= 0.55 and buy_strength > sell_strength:
            reasons = []
            if strong_positive_news: reasons.append(f"positive news ({n_arts} articles, score:{score:.2f})")
            if earnings_catalyst:    reasons.append(f"earnings catalyst ({e_score:.2f})")
            if price_confirms_buy:   reasons.append(f"price up {price_rx['pct_change']:.1f}%")
            return {
                "signal":     "BUY",
                "strength":   round(buy_strength, 2),
                "reason":     " | ".join(reasons),
                "indicators": indicators,
            }

        elif sell_strength >= 0.55 and sell_strength > buy_strength:
            reasons = []
            if strong_negative_news: reasons.append(f"negative news (score:{score:.2f})")
            if price_confirms_sell:  reasons.append(f"price down {price_rx['pct_change']:.1f}%")
            if fade_the_news:        reasons.append("fading the news (buy rumor/sell news)")
            return {
                "signal":     "SELL",
                "strength":   round(sell_strength, 2),
                "reason":     " | ".join(reasons),
                "indicators": indicators,
            }

        return self._no_signal(
            f"Neutral news | score:{score:.2f} articles:{n_arts} "
            f"| Buy:{buy_strength:.0%} Sell:{sell_strength:.0%}"
        )

    def _no_signal(self, reason: str) -> dict:
        return {"signal": "HOLD", "strength": 0.0, "reason": reason, "indicators": {}}
