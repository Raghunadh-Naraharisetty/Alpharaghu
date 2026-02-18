"""
ALPHARAGHU - News & Data Fetcher
Fetches real-time news from multiple sources
"""
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional
import config

logger = logging.getLogger("alpharaghu.news")


class NewsFetcher:
    def __init__(self, alpaca_client=None):
        self.alpaca   = alpaca_client
        self.news_api_key = config.NEWS_API_KEY
        self._cache   = {}  # symbol → (timestamp, articles)
        self._cache_ttl_minutes = 15

    def _is_cached(self, key: str) -> bool:
        if key not in self._cache:
            return False
        age = (datetime.now() - self._cache[key]["time"]).total_seconds() / 60
        return age < self._cache_ttl_minutes

    # ── Alpaca News (Primary - Free with API) ────────────────
    def get_alpaca_news(self, symbols: list, hours: int = 24) -> list:
        if not self.alpaca:
            return []
        try:
            articles = self.alpaca.get_news(symbols, limit=20)
            # Filter to recent
            cutoff = datetime.now() - timedelta(hours=hours)
            recent = []
            for art in articles:
                ts = art.get("created_at")
                if ts:
                    try:
                        if isinstance(ts, str):
                            art_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            art_dt = art_dt.replace(tzinfo=None)
                        else:
                            art_dt = ts
                        if art_dt >= cutoff:
                            recent.append(art)
                    except Exception:
                        recent.append(art)
            return recent
        except Exception as e:
            logger.error(f"Alpaca news error: {e}")
            return []

    # ── NewsAPI.org (Secondary - 100 req/day free) ───────────
    def get_newsapi_news(self, symbol: str, company_name: str = None) -> list:
        if not self.news_api_key:
            return []
        try:
            query = company_name or symbol
            url   = "https://newsapi.org/v2/everything"
            params = {
                "q":        f"{query} stock",
                "sortBy":   "publishedAt",
                "language": "en",
                "pageSize": 10,
                "from":     (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S"),
                "apiKey":   self.news_api_key,
            }
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                articles = []
                for art in data.get("articles", []):
                    articles.append({
                        "headline":   art.get("title", ""),
                        "summary":    art.get("description", ""),
                        "source":     art.get("source", {}).get("name", ""),
                        "created_at": art.get("publishedAt", ""),
                        "url":        art.get("url", ""),
                        "symbols":    [symbol],
                    })
                return articles
        except Exception as e:
            logger.error(f"NewsAPI error for {symbol}: {e}")
        return []

    # ── Combined News ────────────────────────────────────────
    def get_all_news(self, symbol: str, company_name: str = None) -> list:
        """Get news from all sources, deduplicated"""
        cache_key = f"news_{symbol}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]["data"]

        # Alpaca is primary (free, real-time)
        alpaca_news = self.get_alpaca_news([symbol], hours=24)

        # NewsAPI as supplement
        api_news = []
        if not alpaca_news or len(alpaca_news) < 3:
            api_news = self.get_newsapi_news(symbol, company_name)

        # Merge & deduplicate by headline
        all_articles = alpaca_news + api_news
        seen = set()
        unique = []
        for art in all_articles:
            h = art.get("headline", "")[:50]
            if h not in seen:
                seen.add(h)
                unique.append(art)

        self._cache[cache_key] = {"time": datetime.now(), "data": unique}
        return unique

    # ── Market-wide News ─────────────────────────────────────
    def get_market_news(self) -> list:
        """General market news (SPY, QQQ, macro)"""
        return self.get_alpaca_news(["SPY", "QQQ"], hours=6)

    # ── Earnings Calendar ────────────────────────────────────
    def get_upcoming_earnings(self, symbols: list) -> dict:
        """Get earnings dates for watchlist symbols"""
        result = {}
        for sym in symbols:
            try:
                import yfinance as yf
                ticker   = yf.Ticker(sym)
                calendar = ticker.calendar
                if calendar is not None and not calendar.empty:
                    result[sym] = str(calendar.iloc[0, 0])
            except Exception:
                pass
        return result
