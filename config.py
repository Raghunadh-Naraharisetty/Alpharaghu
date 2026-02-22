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
TELEGRAM_CHANNEL_ID   = os.getenv("TELEGRAM_CHANNEL_ID",   "-1003837198055")  # ALPHARAGHU Signals channel

# ── News API ────────────────────────────────────────────────
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# ── Risk Management ─────────────────────────────────────────
MAX_POSITION_SIZE    = float(os.getenv("MAX_POSITION_SIZE", 1000))
MAX_OPEN_POSITIONS   = int(os.getenv("MAX_OPEN_POSITIONS", 5))
RISK_PER_TRADE_PCT   = float(os.getenv("RISK_PER_TRADE_PCT", 2))
STOP_LOSS_PCT        = float(os.getenv("STOP_LOSS_PCT", 2))
TAKE_PROFIT_PCT      = float(os.getenv("TAKE_PROFIT_PCT", 4))

# Position Sizing Method
# "fixed" = uses STOP_LOSS_PCT as fixed % stop (simple, predictable)
# "atr"   = uses ATR x multiplier as dynamic stop (adapts to real volatility)
#   High-volatility stock (UVXY) -> smaller position
#   Low-volatility stock  (JNJ)  -> larger position
#   Both risk the SAME dollar amount per trade
POSITION_SIZE_METHOD  = os.getenv("POSITION_SIZE_METHOD",  "atr")
ATR_STOP_MULTIPLIER   = float(os.getenv("ATR_STOP_MULTIPLIER",   2.0))  # stop   = price - (ATR x 2.0)
ATR_TARGET_MULTIPLIER = float(os.getenv("ATR_TARGET_MULTIPLIER", 4.0))  # target = price + (ATR x 4.0) = 2:1 R:R

# ── Scanner Settings ────────────────────────────────────────
USE_DYNAMIC_SCANNER      = os.getenv("USE_DYNAMIC_SCANNER", "true").lower() == "true"

# Pivot-level stops (S1/S2 as stop, R1 as target) — more precise than fixed %
USE_PIVOT_STOPS          = os.getenv("USE_PIVOT_STOPS", "true").lower() == "true"

# Pre-market gapper mode — minimum gap % to qualify as a tradeable gapper
PREMARKET_MIN_GAP_PCT    = float(os.getenv("PREMARKET_MIN_GAP_PCT", 5.0))
SCAN_INTERVAL_MINUTES    = int(os.getenv("SCAN_INTERVAL_MINUTES", 15))

# ── Static Watchlist (used alongside or instead of scanner) ─
WATCHLIST = [

    # ── Broad Market ETFs ────────────────────────────────────
    "SPY",   # S&P 500 — market benchmark
    "QQQ",   # Nasdaq 100 — tech heavy
    "DIA",   # Dow Jones — blue chips
    "IWM",   # Russell 2000 — small caps, leads big moves

    # ── Volatility ETFs (new!) ───────────────────────────────
    "UVXY",  # 1.5x Long VIX — spikes on market fear, great momentum plays
    "VIXY",  # VIX Short-Term Futures — smoother than UVXY

    # ── Sector ETFs ──────────────────────────────────────────
    "XLK",   # Technology sector
    "XLF",   # Financial sector
    "XLV",   # Healthcare sector
    "XLE",   # Energy sector

    # ── Tech ─────────────────────────────────────────────────
    "AAPL",  # Apple
    "MSFT",  # Microsoft
    "NVDA",  # NVIDIA — most volatile mega cap

    # ── Finance ──────────────────────────────────────────────
    "JPM",   # JPMorgan
    "GS",    # Goldman Sachs
    "BAC",   # Bank of America

    # ── Healthcare ───────────────────────────────────────────
    "UNH",   # UnitedHealth
    "JNJ",   # Johnson & Johnson
    "PFE",   # Pfizer

    # ── Energy ───────────────────────────────────────────────
    "XOM",   # ExxonMobil
    "CVX",   # Chevron
    "OXY",   # Occidental — volatile, Buffett holding

    # ── Commodities via ETFs ─────────────────────────────────
    "GLD",   # Gold
    "SLV",   # Silver
    "USO",   # Oil
    "UNG",   # Natural Gas — highly volatile
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
