"""
ALPHARAGHU - Configuration Manager
Loads all settings from .env file
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Alpaca ──────────────────────────────────────────────────
ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# ── Telegram ────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ── News API ────────────────────────────────────────────────
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# ── Risk Management ─────────────────────────────────────────
MAX_POSITION_SIZE    = float(os.getenv("MAX_POSITION_SIZE", 1000))
MAX_OPEN_POSITIONS   = int(os.getenv("MAX_OPEN_POSITIONS", 5))
RISK_PER_TRADE_PCT   = float(os.getenv("RISK_PER_TRADE_PCT", 2))
STOP_LOSS_PCT        = float(os.getenv("STOP_LOSS_PCT", 2))
TAKE_PROFIT_PCT      = float(os.getenv("TAKE_PROFIT_PCT", 4))

# ── Scanner Settings ────────────────────────────────────────
USE_DYNAMIC_SCANNER      = os.getenv("USE_DYNAMIC_SCANNER", "true").lower() == "true"
SCAN_INTERVAL_MINUTES    = int(os.getenv("SCAN_INTERVAL_MINUTES", 15))

# ── Static Watchlist (used alongside or instead of scanner) ─
WATCHLIST = [
    # Large-cap tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    # Finance
    "JPM", "BAC", "GS",
    # ETFs (commodities/forex proxies on Alpaca)
    "GLD",   # Gold ETF
    "SLV",   # Silver ETF
    "USO",   # Oil ETF
    "UUP",   # US Dollar ETF (forex proxy)
    "FXE",   # Euro ETF
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq 100
]

# ── Strategy Weights (for signal consensus) ─────────────────
STRATEGY_WEIGHTS = {
    "momentum":       0.35,
    "mean_reversion": 0.35,
    "news_sentiment": 0.30,
}

# ── Market Hours (Eastern Time) ─────────────────────────────
MARKET_OPEN_HOUR  = 9
MARKET_OPEN_MIN   = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MIN  = 0
