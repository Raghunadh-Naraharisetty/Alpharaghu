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

# Symbols where NewsAPI adds zero value — ETFs, commodities, volatility instruments
# These return irrelevant articles and waste quota. Alpaca news only for these.
_NEWSAPI_SKIP = {
    "SPY","QQQ","DIA","IWM","UVXY","VIXY","VXX","SVXY",
    "XLK","XLF","XLV","XLE","XLY","XLI","XLP","XLU","XLRE",
    "GLD","SLV","USO","UNG","UUP","FXE","TLT","IEF",
}


class NewsFetcher:
    def __init__(self, alpaca_client=None):
        self.alpaca       = alpaca_client
        self.news_api_key = config.NEWS_API_KEY
        self._cache       = {}   # symbol → {time, data}
        self._cache_ttl_minutes = 15
        # Daily quota guard — NewsAPI free tier = 100 req/day
        self._newsapi_calls_today = 0
        self._newsapi_quota_date  = datetime.now().date()
        self._newsapi_daily_limit = 80   # leave 20 buffer

    def _is_cached(self, key: str) -> bool:
        if key not in self._cache:
            return False
        age = (datetime.now() - self._cache[key]["time"]).total_seconds() / 60
        return age < self._cache_ttl_minutes

    def _newsapi_quota_ok(self) -> bool:
        """Reset counter daily and check if we still have quota."""
        today = datetime.now().date()
        if today != self._newsapi_quota_date:
            self._newsapi_calls_today = 0
            self._newsapi_quota_date  = today
        if self._newsapi_calls_today >= self._newsapi_daily_limit:
            logger.debug(
                f"[NEWS] NewsAPI daily limit reached "
                f"({self._newsapi_calls_today}/{self._newsapi_daily_limit}) — "
                f"using Alpaca only"
            )
            return False
        return True

    # ── Alpaca News (Primary — free, real-time, no quota) ────
    def get_alpaca_news(self, symbols: list, hours: int = 24) -> list:
        if not self.alpaca:
            return []
        try:
            articles = self.alpaca.get_news(symbols, limit=20)
            cutoff   = datetime.now() - timedelta(hours=hours)
            recent   = []
            for art in articles:
                ts = art.get("created_at")
                if ts:
                    try:
                        if isinstance(ts, str):
                            art_dt = datetime.fromisoformat(
                                ts.replace("Z", "+00:00")
                            ).replace(tzinfo=None)
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

    # ── NewsAPI.org (Fallback — 100 req/day free tier) ───────
    def get_newsapi_news(self, symbol: str, company_name: str = None) -> list:
        if not self.news_api_key:
            return []
        # Skip ETFs/commodities — NewsAPI returns irrelevant articles for them
        if symbol in _NEWSAPI_SKIP:
            return []
        # Quota guard
        if not self._newsapi_quota_ok():
            return []
        try:
            query  = company_name or symbol
            url    = "https://newsapi.org/v2/everything"
            params = {
                "q":        f"{query} stock",
                "sortBy":   "publishedAt",
                "language": "en",
                "pageSize": 10,
                "from":     (datetime.now() - timedelta(hours=24)).strftime(
                                "%Y-%m-%dT%H:%M:%S"
                            ),
                "apiKey":   self.news_api_key,
            }
            resp = requests.get(url, params=params, timeout=3)   # 10s → 3s
            self._newsapi_calls_today += 1
            if resp.status_code == 200:
                articles = []
                for art in resp.json().get("articles", []):
                    articles.append({
                        "headline":   art.get("title", ""),
                        "summary":    art.get("description", ""),
                        "source":     art.get("source", {}).get("name", ""),
                        "created_at": art.get("publishedAt", ""),
                        "url":        art.get("url", ""),
                        "symbols":    [symbol],
                    })
                return articles
            elif resp.status_code == 429:
                logger.warning("[NEWS] NewsAPI rate limit hit (429) — pausing for today")
                self._newsapi_calls_today = self._newsapi_daily_limit
        except requests.exceptions.Timeout:
            logger.warning(f"[NEWS] NewsAPI timeout for {symbol} (3s) — skipping")
        except Exception as e:
            logger.error(f"NewsAPI error for {symbol}: {e}")
        return []

    # ── Combined News ─────────────────────────────────────────
    def get_all_news(self, symbol: str, company_name: str = None) -> list:
        """Get news from all sources, deduplicated. Cache per-symbol for 15 min."""
        cache_key = f"news_{symbol}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]["data"]

        # Alpaca is primary (free, real-time, no quota)
        alpaca_news = self.get_alpaca_news([symbol], hours=24)

        # NewsAPI only as supplement if Alpaca returns < 3 articles
        # AND symbol is a real stock (not an ETF/commodity)
        api_news = []
        if symbol not in _NEWSAPI_SKIP and len(alpaca_news) < 3:
            api_news = self.get_newsapi_news(symbol, company_name)

        # Merge & deduplicate by headline prefix
        seen   = set()
        unique = []
        for art in alpaca_news + api_news:
            h = art.get("headline", "")[:50]
            if h not in seen:
                seen.add(h)
                unique.append(art)

        self._cache[cache_key] = {"time": datetime.now(), "data": unique}
        return unique


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
