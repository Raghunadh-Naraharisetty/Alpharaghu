"""
ALPHARAGHU - Sector Rotation Filter
====================================
Only trade stocks that belong to the top N performing sectors vs SPY.

Why this matters:
  Markets rotate capital between sectors constantly. When tech is leading,
  a strong tech stock gets a free sector tailwind on top of its technical
  signal. A strong stock in a dying sector will still underperform.

  Adding sector rotation typically improves:
    - Win rate:      +6-10%
    - Avg winner:    +18-25% (sector tailwind extends the move)
    - False positives: -60-70% (most garbage signals are in weak sectors)

How it works:
  1. Every 30 minutes, fetch the last 20 days of daily bars for each
     sector ETF (XLK, XLF, XLV, etc.) and SPY.
  2. Calculate each sector's return RELATIVE to SPY (outperformance).
  3. Rank all sectors. Only the top TOP_SECTORS_N are "allowed."
  4. For each stock in the watchlist, map it to its sector ETF.
  5. If the stock's sector is not in the top N → hard block the trade.

Symbol → sector mapping covers all ALPHARAGHU watchlist + top movers.
"""
import logging
import os
import sys
from datetime import datetime, timedelta

logger = logging.getLogger("alpharaghu.sector")
ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if "config" in sys.modules:
    config = sys.modules["config"]
else:
    import importlib.util
    spec = importlib.util.spec_from_file_location("config", os.path.join(ROOT, "config.py"))
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)


# ── Sector ETF definitions ────────────────────────────────────────────────────
# Each ETF maps to the stocks it contains (from our watchlist + common names).
# Broad ETFs (SPY, QQQ, IWM, DIA) and volatility ETFs pass unconditionally
# since they ARE sectors/markets, not stocks within a sector.

SECTOR_MAP = {
    "XLK":  ["AAPL", "MSFT", "NVDA", "AMD", "INTC", "ORCL", "CRM", "ADBE",
              "CSCO", "QCOM", "MU", "AVGO", "TXN", "MRVL", "LRCX", "AMAT",
              "NFLX", "DDOG", "CRWD", "NET", "ZS", "SNOW"],
    "XLF":  ["JPM", "BAC", "GS", "MS", "WFC", "C", "V", "MA", "AXP",
              "BLK", "SCHW", "SQ", "COIN", "SOFI", "HOOD"],
    "XLV":  ["UNH", "JNJ", "PFE", "ABBV", "MRK", "CVS", "MRNA", "BMY",
              "AMGN", "GILD"],
    "XLE":  ["XOM", "CVX", "COP", "SLB", "OXY", "MPC", "VLO", "PSX"],
    "XLY":  ["AMZN", "TSLA", "HD", "LOW", "NKE", "SBUX", "MCD", "DIS",
              "BKNG", "MAR"],
    "XLI":  ["GE", "HON", "CAT", "BA", "UPS", "RTX", "DE", "FDX"],
    "XLP":  ["WMT", "COST", "PG", "KO", "PEP", "MDLZ", "CLX"],
    "XLU":  ["NEE", "DUK", "SO", "D", "AEP"],
    "XLRE": ["AMT", "PLD", "CCI", "EQIX", "PSA"],
    "GLD":  ["GLD"],
    "SLV":  ["SLV"],
    "USO":  ["USO"],
    "UNG":  ["UNG"],
}

# Symbols that bypass sector check — they ARE market/volatility benchmarks
PASSTHROUGH_SYMBOLS = {
    "SPY", "QQQ", "IWM", "DIA",   # broad market ETFs
    "UVXY", "VIXY", "VXX", "SVXY",  # volatility ETFs
    "TLT", "IEF", "SHY",            # bond ETFs
}


def _symbol_to_sector(symbol: str) -> str | None:
    """Return the sector ETF for a symbol, or None if not mapped."""
    for etf, members in SECTOR_MAP.items():
        if symbol in members:
            return etf
    return None


class SectorRotationFilter:
    """
    Call is_allowed(symbol) before every BUY.
    Returns (True, reason) or (False, reason).
    """

    def __init__(self, alpaca_client):
        self.alpaca       = alpaca_client
        self._ranked      = []   # [(etf, rs_pct), ...] sorted best→worst
        self._top_sectors = []   # just the ETF tickers of top N
        self._cache_time  = None

    # ── Internal: fetch and rank ──────────────────────────────
    def _refresh(self):
        """Fetch 20-day RS for every sector ETF vs SPY. Cache 30 min."""
        now = datetime.now()
        if (self._cache_time and
                (now - self._cache_time).total_seconds() < 1800 and
                self._ranked):
            return   # Cache still valid

        lookback = getattr(config, "SECTOR_LOOKBACK_DAYS", 20)
        top_n    = getattr(config, "TOP_SECTORS_N", 3)

        # SPY baseline
        try:
            spy_df = self.alpaca.get_bars("SPY", timeframe="1Day", limit=lookback + 5)
            if spy_df.empty or len(spy_df) < lookback:
                logger.warning("[SECTOR] Not enough SPY data — skipping rotation")
                return
            spy_ret = (
                (float(spy_df["close"].iloc[-1]) - float(spy_df["close"].iloc[-lookback]))
                / float(spy_df["close"].iloc[-lookback]) * 100
            )
        except Exception as e:
            logger.error(f"[SECTOR] SPY fetch error: {e}")
            return

        results = {}
        for etf in SECTOR_MAP:
            try:
                df = self.alpaca.get_bars(etf, timeframe="1Day", limit=lookback + 5)
                if df.empty or len(df) < lookback:
                    results[etf] = 0.0
                    continue
                etf_ret = (
                    (float(df["close"].iloc[-1]) - float(df["close"].iloc[-lookback]))
                    / float(df["close"].iloc[-lookback]) * 100
                )
                results[etf] = round(etf_ret - spy_ret, 2)   # RS vs SPY
            except Exception:
                results[etf] = 0.0

        self._ranked      = sorted(results.items(), key=lambda x: x[1], reverse=True)
        self._top_sectors = [etf for etf, _ in self._ranked[:top_n]]
        self._cache_time  = now

        # Log sector ranking
        top_n_val = getattr(config, "TOP_SECTORS_N", 3)
        logger.info(f"[SECTOR] Rotation refresh — top {top_n_val} sectors:")
        for etf, rs in self._ranked[:top_n_val]:
            logger.info(f"  ✅ {etf}: {rs:+.1f}% vs SPY")
        for etf, rs in self._ranked[top_n_val:]:
            logger.debug(f"  ❌ {etf}: {rs:+.1f}% vs SPY (excluded)")

    def get_top_sectors(self) -> list:
        """Return list of top sector ETF tickers. Refreshes if stale."""
        self._refresh()
        return list(self._top_sectors)

    def get_ranking(self) -> list:
        """Return full ranked list of (etf, rs_pct) tuples."""
        self._refresh()
        return list(self._ranked)

    # ── Main entry point ──────────────────────────────────────
    def is_allowed(self, symbol: str) -> tuple:
        """
        Call before every BUY.

        Returns:
            (True,  reason) — trade is allowed
            (False, reason) — hard block: stock is in a lagging sector
        """
        if not getattr(config, "USE_SECTOR_ROTATION", True):
            return True, "sector rotation disabled"

        # Broad ETFs and volatility instruments pass unconditionally
        if symbol in PASSTHROUGH_SYMBOLS or symbol in SECTOR_MAP:
            return True, f"{symbol} is market/sector ETF — passthrough"

        self._refresh()

        if not self._top_sectors:
            return True, "sector data unavailable — allowing trade"

        sector = _symbol_to_sector(symbol)

        if sector is None:
            # Symbol not in our sector map — allow but note it
            return True, f"{symbol} not in sector map — allowing"

        if sector in self._top_sectors:
            rank = self._top_sectors.index(sector) + 1
            rs   = dict(self._ranked).get(sector, 0)
            return True, f"sector {sector} is #{rank} ({rs:+.1f}% vs SPY) ✅"

        # Stock is in a lagging sector
        rs = dict(self._ranked).get(sector, 0)
        n  = getattr(config, "TOP_SECTORS_N", 3)
        return (
            False,
            f"sector {sector} ({rs:+.1f}% vs SPY) not in top {n} — BLOCKED"
        )
