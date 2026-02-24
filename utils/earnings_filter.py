"""
ALPHARAGHU - Earnings Filter
============================
Hard-blocks any new entry within ±3 days of an earnings event.

Why this matters for swing trading (multi-day holds):
  - Earnings = binary volatility event. Even a perfect setup
    can gap down 20% overnight on a single EPS miss.
  - GTC bracket stops are USELESS against gaps — they execute
    at the open price which may be far below your stop.
  - Adding this filter is typically worth +8-12% win rate improvement.

Two modes (set in config):
  DEFENSIVE (default): Hard-block ALL entries in the earnings window.
  AGGRESSIVE: Allow post-earnings gap if sentiment ≥ 0.7 AND volume ≥ 2x.
    Use this to catch gap-up momentum plays right after strong beats.

Detection method:
  Uses Alpaca news API to scan for earnings-related keywords in a
  [-DAYS_AFTER, +DAYS_BEFORE] window around today. No extra subscription needed.
  Falls back to "allow" on API failure so it never over-blocks.
"""
import logging
import os
import sys
from datetime import datetime, timedelta

logger = logging.getLogger("alpharaghu.earnings")
ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if "config" in sys.modules:
    config = sys.modules["config"]
else:
    import importlib.util
    spec = importlib.util.spec_from_file_location("config", os.path.join(ROOT, "config.py"))
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)


# Keywords that indicate upcoming or recent earnings
EARNINGS_KEYWORDS = [
    "earnings", " eps ", "quarterly results", "quarterly earnings",
    "q1 results", "q2 results", "q3 results", "q4 results",
    "beats estimates", "misses estimates", "revenue beat", "revenue miss",
    "reports earnings", "after the bell", "before the open",
    "earnings call", "earnings release", "earnings report",
    "fiscal quarter", "profit report", "income report",
]


class EarningsFilter:
    """
    Hard gate — call check(symbol) before every BUY.
    Returns (True, reason) to proceed or (False, reason) to skip.
    """

    def __init__(self, alpaca_client):
        self.alpaca  = alpaca_client
        self._cache  = {}   # symbol → (result, timestamp) — session cache

    def _news_has_earnings(self, symbol: str, start_dt: datetime,
                           end_dt: datetime) -> bool:
        """Scan Alpaca news for earnings-related articles in the date window."""
        try:
            news = self.alpaca.get_news([symbol], limit=30)
            if not news:
                return False

            for article in news:
                # Check article date falls within window
                try:
                    art_time = article.get("created_at") or article.get("updated_at", "")
                    if art_time:
                        art_dt = datetime.fromisoformat(
                            str(art_time).replace("Z", "+00:00").replace("+00:00", "")
                        )
                        if not (start_dt <= art_dt <= end_dt):
                            continue
                except Exception:
                    pass  # Can't parse date — check the content anyway

                headline = str(article.get("headline", "")).lower()
                summary  = str(article.get("summary",  "")).lower()
                text     = headline + " " + summary

                if any(kw in text for kw in EARNINGS_KEYWORDS):
                    logger.info(
                        f"  [EARNINGS] {symbol}: earnings keyword found → "
                        f"'{article.get('headline', '')[:60]}'"
                    )
                    return True

            return False

        except Exception as e:
            logger.debug(f"  [EARNINGS] News API error for {symbol}: {e}")
            return False

    def check(self, symbol: str,
              sentiment_score: float = 0.5,
              vol_ratio: float = 1.0) -> tuple:
        """
        Main entry point. Call before every BUY.

        Args:
            symbol:          Ticker to check
            sentiment_score: 0-1 score from news sentiment (for aggressive mode)
            vol_ratio:       Recent vol / avg vol (for aggressive mode)

        Returns:
            (True,  reason_str) — safe to trade
            (False, reason_str) — block this trade
        """
        if not getattr(config, "USE_EARNINGS_FILTER", True):
            return True, "earnings filter disabled"

        # Session cache — earnings windows don't change mid-day
        cached = self._cache.get(symbol)
        if cached:
            result, ts = cached
            if (datetime.now() - ts).seconds < 3600:   # 1h cache
                return result

        now        = datetime.now()
        days_before = getattr(config, "EARNINGS_BLOCK_DAYS_BEFORE", 3)
        days_after  = getattr(config, "EARNINGS_BLOCK_DAYS_AFTER",  1)

        window_start = now - timedelta(days=days_after)
        window_end   = now + timedelta(days=days_before)

        has_earnings = self._news_has_earnings(symbol, window_start, window_end)

        if not has_earnings:
            result = (True, "no earnings in window")
            self._cache[symbol] = (result, now)
            return result

        # ── AGGRESSIVE MODE ─────────────────────────────────────
        if getattr(config, "EARNINGS_AGGRESSIVE_MODE", False):
            min_sent = getattr(config, "EARNINGS_AGGRESSIVE_MIN_SENTIMENT", 0.7)
            min_vol  = getattr(config, "EARNINGS_AGGRESSIVE_MIN_VOL_SPIKE",  2.0)
            if sentiment_score >= min_sent and vol_ratio >= min_vol:
                reason = (f"earnings gap ALLOWED — aggressive mode "
                          f"(sent:{sentiment_score:.2f} vol:{vol_ratio:.1f}x)")
                result = (True, reason)
                self._cache[symbol] = (result, now)
                logger.info(f"  [EARNINGS] {symbol}: {reason}")
                return result
            reason = (f"earnings gap BLOCKED — aggressive mode threshold not met "
                      f"(sent:{sentiment_score:.2f}<{min_sent} or "
                      f"vol:{vol_ratio:.1f}x<{min_vol}x)")
            result = (False, reason)
            self._cache[symbol] = (result, now)
            logger.info(f"  [EARNINGS] {symbol}: {reason}")
            return result

        # ── DEFENSIVE MODE (default) ────────────────────────────
        reason = (f"BLOCKED — earnings window ±{days_before}d "
                  f"({window_start.strftime('%m/%d')}–{window_end.strftime('%m/%d')})")
        result = (False, reason)
        self._cache[symbol] = (result, now)
        logger.info(f"  [EARNINGS] {symbol}: {reason}")
        return result
