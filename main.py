"""
ALPHARAGHU - Main Trading Engine
Windows-compatible, mobile-controllable via Telegram
"""
import sys
import os
import importlib.util
import logging
import time
import schedule
import json
from datetime import datetime

os.environ["PYTHONUTF8"] = "1"

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)

# ── Logging ──────────────────────────────────────────────────
log_format = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s - %(message)s")
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_format)
file_handler = logging.FileHandler(os.path.join(ROOT, "logs", "alpharaghu.log"), encoding="utf-8")
file_handler.setFormatter(log_format)
logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])
logger = logging.getLogger("alpharaghu.engine")


# ── Module Loader ─────────────────────────────────────────────
def load_module(name, *path_parts):
    abs_path = os.path.join(ROOT, *path_parts)
    spec     = importlib.util.spec_from_file_location(name, abs_path)
    mod      = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


logger.info("Loading modules...")
config       = load_module("config",       "config.py")
alpaca_mod   = load_module("alpaca_client","broker", "alpaca_client.py")
s1_mod       = load_module("strategy1",   "strategies", "strategy1_momentum.py")
s2_mod       = load_module("strategy2",   "strategies", "strategy2_mean_reversion.py")
s3_mod       = load_module("strategy3",   "strategies", "strategy3_news_sentiment.py")
combiner_mod = load_module("combiner",    "strategies", "__init__.py")
tg_mod       = load_module("telegram_bot","notifications", "telegram_bot.py")
news_mod     = load_module("news_fetcher","data", "news_fetcher.py")

AlpacaClient         = alpaca_mod.AlpacaClient
StrategyCombiner     = combiner_mod.StrategyCombiner
TelegramBot          = tg_mod.TelegramBot
TelegramCommandHandler = tg_mod.TelegramCommandHandler
NewsFetcher          = news_mod.NewsFetcher
logger.info("All modules loaded OK")


# ── Signal Logger (feeds Streamlit dashboard) ─────────────────
SIGNAL_LOG = os.path.join(ROOT, "logs", "signals.json")
STATE_FILE  = os.path.join(ROOT, "logs", "bot_state.json")

def log_signal(result: dict):
    signals = []
    try:
        if os.path.exists(SIGNAL_LOG):
            with open(SIGNAL_LOG) as f:
                signals = json.load(f)
    except Exception:
        pass
    signals.append({
        "symbol":     result.get("symbol"),
        "signal":     result.get("signal"),
        "confidence": result.get("confidence"),
        "consensus":  result.get("consensus"),
        "reason":     " | ".join(result.get("reason_lines", []))[:200],
        "time":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    signals = signals[-200:]  # Keep last 200
    with open(SIGNAL_LOG, "w") as f:
        json.dump(signals, f)

def is_bot_paused() -> bool:
    """Check if Telegram /stop command was issued"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                state = json.load(f)
            return not state.get("running", True)
    except Exception:
        pass
    return False


# ── Engine ─────────────────────────────────────────────────────
class AlpharaghuEngine:

    def __init__(self):
        logger.info("=" * 60)
        logger.info("  ALPHARAGHU - Algo Trading Engine")
        logger.info("=" * 60)

        self.alpaca   = AlpacaClient()
        self.telegram = TelegramBot()
        self.combiner = StrategyCombiner()
        self.news     = NewsFetcher(alpaca_client=self.alpaca)

        self.active_signals = {}
        self.scan_count     = 0

        # Start Telegram command handler (mobile control)
        self.cmd_handler = TelegramCommandHandler(self.telegram, engine_ref=self)
        self.cmd_handler.start_background()
        logger.info("Telegram command handler running. Control bot from your phone!")

    def get_symbols_to_scan(self):
        symbols = list(config.WATCHLIST)
        if config.USE_DYNAMIC_SCANNER:
            top_movers = self.alpaca.get_top_movers(top_n=15)
            symbols    = list(set(symbols + top_movers))
        logger.info(f"Scanning {len(symbols)} symbols")
        return symbols

    def run_scan(self):
        if is_bot_paused():
            logger.info("Bot paused by Telegram /stop command - skipping scan")
            return

        if not self.alpaca.is_market_open():
            logger.info("Market closed - skipping scan")
            return

        self.scan_count += 1
        logger.info(f"--- Scan #{self.scan_count} | {datetime.now().strftime('%H:%M:%S')} ---")

        symbols        = self.get_symbols_to_scan()
        open_positions = self.alpaca.get_open_position_count()

        for symbol in symbols:
            try:
                self._analyze_symbol(symbol, open_positions)
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                self.telegram.send_error(f"{symbol}: {str(e)[:200]}")

    def _analyze_symbol(self, symbol, open_positions):
        df_15min = self.alpaca.get_bars(symbol, timeframe="15Min", limit=250)
        df_daily = self.alpaca.get_bars(symbol, timeframe="1Day",  limit=252)

        if df_15min.empty or len(df_15min) < 50:
            logger.debug(f"  {symbol}: insufficient data, skipping")
            return

        news_articles = self.news.get_all_news(symbol)
        result        = self.combiner.run(symbol, df_15min, df_daily, news_articles)

        signal     = result["signal"]
        confidence = result["confidence"]
        consensus  = result["consensus"]

        logger.info(f"  {symbol}: {signal} | conf:{confidence:.0%} | consensus:{consensus}/3")

        if signal == "HOLD":
            return

        last_sig  = self.active_signals.get(symbol, {})
        last_time = last_sig.get("time", datetime(2000, 1, 1))
        if last_sig.get("signal") == signal and (datetime.now() - last_time).seconds < 1800:
            logger.debug(f"  {symbol}: duplicate signal suppressed")
            return

        current_position = self.alpaca.get_position(symbol)
        price = df_15min["close"].iloc[-1]

        if signal == "BUY" and not current_position:
            if open_positions < config.MAX_OPEN_POSITIONS:
                self._execute_buy(symbol, price, result)

        elif signal == "SELL" and current_position:
            self._execute_sell(symbol, price, result, current_position)

        self.telegram.send_signal(result)
        log_signal(result)  # Save to dashboard log
        self.active_signals[symbol] = {"signal": signal, "time": datetime.now()}

    def _execute_buy(self, symbol, price, result):
        stop_price   = price * (1 - config.STOP_LOSS_PCT   / 100)
        target_price = price * (1 + config.TAKE_PROFIT_PCT / 100)
        qty          = self.alpaca.calculate_position_size(price, stop_price)

        if qty < 0.01:
            logger.warning(f"  {symbol}: position size too small, skipping")
            return

        order = self.alpaca.place_market_order(
            symbol=symbol, qty=qty, side="buy",
            stop_loss=stop_price, take_profit=target_price,
        )
        if order:
            logger.info(f"  [BUY FILLED] {qty:.2f} x {symbol} @ ~${price:.2f}")
            result["targets"] = {
                "entry":  round(price, 2),
                "stop":   round(stop_price, 2),
                "target": round(target_price, 2),
            }

    def _execute_sell(self, symbol, price, result, position):
        self.alpaca.close_position(symbol)
        try:
            pl = float(position.unrealized_pl)
            logger.info(f"  [SELL FILLED] {symbol} | P&L: ${pl:+.2f}")
        except Exception:
            logger.info(f"  [SELL FILLED] {symbol}")

    def send_daily_summary(self):
        try:
            account   = self.alpaca.get_account()
            positions = self.alpaca.get_positions()
            self.telegram.send_portfolio_summary(account, positions)
        except Exception as e:
            logger.error(f"Daily summary error: {e}")

    def run(self):
        logger.info("Engine starting...")
        self.telegram.send_startup_message()

        schedule.every(config.SCAN_INTERVAL_MINUTES).minutes.do(self.run_scan)
        schedule.every().day.at("16:05").do(self.send_daily_summary)

        self.run_scan()

        logger.info(f"Scanning every {config.SCAN_INTERVAL_MINUTES} min. Press Ctrl+C to stop.")
        try:
            while True:
                schedule.run_pending()
                time.sleep(30)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user (Ctrl+C).")


if __name__ == "__main__":
    engine = AlpharaghuEngine()
    engine.run()
