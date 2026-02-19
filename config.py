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

    # ── Broad Market ETFs (market compass) ─────────────────
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq 100
    "DIA",   # Dow Jones
    "IWM",   # Russell 2000 small caps

    # ── Mega Cap Tech (highest news flow) ───────────────────
    "AAPL",  # Apple
    "MSFT",  # Microsoft
    "NVDA",  # NVIDIA — AI chip leader, most volatile
    "GOOGL", # Alphabet
    "AMZN",  # Amazon
    "META",  # Meta
    "TSLA",  # Tesla

    # ── Growth Tech (strong movers) ─────────────────────────
    "AMD",   # AMD — NVIDIA rival
    "ORCL",  # Oracle — cloud/AI
    "NFLX",  # Netflix
    "PLTR",  # Palantir — AI/data, volatile
    "APP",   # AppLovin — AI ad tech, big mover
    "ARM",   # ARM Holdings — chip design
    "CRM",   # Salesforce

    # ── Finance ─────────────────────────────────────────────
    "JPM",   # JPMorgan
    "BAC",   # Bank of America
    "GS",    # Goldman Sachs
    "V",     # Visa
    "MA",    # Mastercard
    "PYPL",  # PayPal
    "COIN",  # Coinbase — crypto proxy, high volatility

    # ── Healthcare ───────────────────────────────────────────
    "UNH",   # UnitedHealth
    "LLY",   # Eli Lilly — weight loss drugs, hot stock
    "ABBV",  # AbbVie
    "JNJ",   # Johnson & Johnson
    "MRK",   # Merck
    "PFE",   # Pfizer

    # ── Energy ──────────────────────────────────────────────
    "XOM",   # ExxonMobil
    "CVX",   # Chevron
    "OXY",   # Occidental — Buffett holding, volatile
    "COP",   # ConocoPhillips
    "SLB",   # Schlumberger

    # ── Consumer ────────────────────────────────────────────
    "WMT",   # Walmart
    "COST",  # Costco
    "HD",    # Home Depot
    "MCD",   # McDonald's
    "SBUX",  # Starbucks
    "TMUS",  # T-Mobile

    # ── Sector ETFs (trade entire sectors) ──────────────────
    "XLK",   # Technology sector
    "XLF",   # Financial sector
    "XLV",   # Healthcare sector
    "XLE",   # Energy sector
    "XLY",   # Consumer discretionary

    # ── Commodities via ETFs ─────────────────────────────────
    "GLD",   # Gold
    "SLV",   # Silver
    "USO",   # Oil
    "UNG",   # Natural Gas — highly volatile
    "PDBC",  # Diversified commodities

    # ── Forex via ETFs ───────────────────────────────────────
    "UUP",   # US Dollar index
    "FXE",   # Euro
    "FXY",   # Japanese Yen
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

# ── Risk Management (Advanced) ───────────────────────────────
# Trailing Stop — activates after X% profit, trails by Y%
TRAILING_STOP_ACTIVATION_PCT = 2.0   # Activate trailing stop after 2% profit
TRAILING_STOP_DISTANCE_PCT   = 1.0   # Trail 1% below peak price

# Circuit Breakers (from friend's system — improved)
MAX_DRAWDOWN_PCT   = 10.0  # Emergency halt if portfolio drops 10% from peak
MAX_DAILY_LOSS_PCT =  5.0  # Stop trading if day loss exceeds 5%

# Trade Cooldown — prevents re-entering same symbol too soon
TRADE_COOLDOWN_HOURS = 1.0  # Wait 1 hour before trading same symbol again

# Multi-Timeframe Trend Filter — only trade in direction of daily trend
USE_MTF_FILTER = True  # Check daily EMA20/EMA50 before entering on 15min signal
