"""
ALPHARAGHU - Main Trading Engine
Scan notifications to Telegram + mobile commands
"""
import sys, os, importlib.util, logging, time, schedule, json
from datetime import datetime

os.environ["PYTHONUTF8"] = "1"
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)

# ── Logging ──────────────────────────────────────────────────
fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s - %(message)s")
ch  = logging.StreamHandler(sys.stdout)
ch.setFormatter(fmt)
fh  = logging.FileHandler(os.path.join(ROOT, "logs", "alpharaghu.log"), encoding="utf-8")
fh.setFormatter(fmt)
logging.basicConfig(level=logging.INFO, handlers=[ch, fh])
logger = logging.getLogger("alpharaghu.engine")

# ── Module loader ────────────────────────────────────────────
def load(name, *parts):
    path = os.path.join(ROOT, *parts)
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

logger.info("Loading modules...")
config       = load("config",        "config.py")
alpaca_mod   = load("alpaca_client", "broker",         "alpaca_client.py")
_            = load("strategy1",     "strategies",     "strategy1_momentum.py")
_            = load("strategy2",     "strategies",     "strategy2_mean_reversion.py")
_            = load("strategy3",     "strategies",     "strategy3_news_sentiment.py")
combiner_mod = load("combiner",      "strategies",     "__init__.py")
tg_mod       = load("telegram_bot",  "notifications",  "telegram_bot.py")
news_mod     = load("news_fetcher",  "data",           "news_fetcher.py")

AlpacaClient           = alpaca_mod.AlpacaClient
StrategyCombiner       = combiner_mod.StrategyCombiner
TelegramBot            = tg_mod.TelegramBot
TelegramCommandHandler = tg_mod.TelegramCommandHandler
NewsFetcher            = news_mod.NewsFetcher
logger.info("All modules loaded OK")

# ── Signal & state log helpers ───────────────────────────────
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
    with open(SIGNAL_LOG, "w") as f:
        json.dump(signals[-200:], f)

def is_paused() -> bool:
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return not json.load(f).get("running", True)
    except Exception:
        pass
    return False


# ── Engine ────────────────────────────────────────────────────
class AlpharaghuEngine:

    def __init__(self):
        logger.info("=" * 60)
        logger.info("  ALPHARAGHU - Algo Trading Engine")
        logger.info("=" * 60)

        self.alpaca   = AlpacaClient()
        self.telegram = TelegramBot()
        self.combiner = StrategyCombiner()
        self.news     = NewsFetcher(alpaca_client=self.alpaca)

        self.scan_count   = 0
        self.signal_count = 0
        self.active_signals = {}

        # Start Telegram command handler (mobile /start /stop /status)
        self.cmd_handler = TelegramCommandHandler(self.telegram, engine_ref=self)
        self.cmd_handler.start_background()
        logger.info("[CMD] Telegram commands ready (/start /stop /status /positions /help)")

    def get_symbols(self) -> list:
        symbols = list(config.WATCHLIST)
        if config.USE_DYNAMIC_SCANNER:
            symbols = list(set(symbols + self.alpaca.get_top_movers(top_n=15)))
        return symbols

    def run_scan(self):
        if is_paused():
            logger.info("Bot paused (/stop received) - skipping scan")
            return
        if not self.alpaca.is_market_open():
            logger.info("Market closed - skipping scan")
            return

        self.scan_count += 1
        symbols        = self.get_symbols()
        open_positions = self.alpaca.get_open_position_count()
        scan_signals   = []   # signals only (BUY/SELL)
        all_results    = []   # every symbol result for "near signals"

        logger.info(f"--- Scan #{self.scan_count} | {len(symbols)} symbols ---")

        for symbol in symbols:
            try:
                result = self._analyze_symbol(symbol, open_positions)
                if result:
                    all_results.append(result)
                    if result.get("signal") in ("BUY", "SELL"):
                        scan_signals.append(result)
                        self.signal_count += 1
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"Error on {symbol}: {e}")

        # Send per-scan summary to Telegram
        try:
            acct = self.alpaca.get_account()
            self.telegram.send_scan_summary(
                scan_num=self.scan_count,
                checked=len(symbols),
                total=len(symbols),
                signals=scan_signals,
                account=acct,
                scan_results=all_results,
            )
        except Exception as e:
            logger.error(f"Scan summary send error: {e}")

    def _analyze_symbol(self, symbol: str, open_positions: int):
        df_15  = self.alpaca.get_bars(symbol, timeframe="15Min", limit=250)
        df_day = self.alpaca.get_bars(symbol, timeframe="1Day",  limit=252)

        if df_15.empty or len(df_15) < 50:
            return None

        news   = self.news.get_all_news(symbol)
        result = self.combiner.run(symbol, df_15, df_day, news)

        signal = result["signal"]
        conf   = result["confidence"]
        cons   = result["consensus"]
        bc     = result.get("buy_confidence", 0)
        sc     = result.get("sell_confidence", 0)

        # Show near-signals in log too (buy or sell conf > 25%)
        if bc > 0.25 or sc > 0.25:
            logger.info(f"  {symbol}: {signal} | {conf:.0%} | {cons}/3 "
                       f"[BUY:{bc:.0%} SELL:{sc:.0%}] <-- NEAR SIGNAL")
        else:
            logger.info(f"  {symbol}: {signal} | {conf:.0%} | {cons}/3")

        if signal == "HOLD":
            return result   # Return HOLD too so near-signals can be tracked

        # Deduplicate within 30 min
        last = self.active_signals.get(symbol, {})
        if (last.get("signal") == signal and
                (datetime.now() - last.get("time", datetime(2000,1,1))).seconds < 1800):
            return None

        price = df_15["close"].iloc[-1]
        pos   = self.alpaca.get_position(symbol)

        if signal == "BUY" and not pos and open_positions < config.MAX_OPEN_POSITIONS:
            stop   = price * (1 - config.STOP_LOSS_PCT   / 100)
            target = price * (1 + config.TAKE_PROFIT_PCT / 100)
            qty    = self.alpaca.calculate_position_size(price, stop)
            if qty >= 0.01:
                order = self.alpaca.place_market_order(symbol, qty, "buy", stop, target)
                if order:
                    result["targets"] = {
                        "entry": round(price, 2),
                        "stop":  round(stop, 2),
                        "target": round(target, 2),
                    }
                    self.telegram.send_signal(result)

        elif signal == "SELL" and pos:
            self.alpaca.close_position(symbol)
            self.telegram.send_signal(result)

        log_signal(result)
        self.active_signals[symbol] = {"signal": signal, "time": datetime.now()}
        return result

    def send_daily_summary(self):
        try:
            self.telegram.send_portfolio_summary(
                self.alpaca.get_account(),
                self.alpaca.get_positions()
            )
        except Exception as e:
            logger.error(f"Daily summary error: {e}")

    def run(self):
        logger.info("Engine starting...")
        symbols = self.get_symbols()
        self.telegram.send_startup(len(symbols), symbols)

        # Log all positions including manually placed ones
        positions = self.alpaca.get_positions()
        if positions:
            logger.info(f"  Found {len(positions)} existing position(s):")
            for p in positions:
                pl = float(p.unrealized_pl)
                logger.info(f"    {p.symbol}: {p.qty} shares @ "
                           f"${float(p.avg_entry_price):.2f} | P&L: ${pl:+.2f}")
        else:
            logger.info("  No existing positions")

        schedule.every(config.SCAN_INTERVAL_MINUTES).minutes.do(self.run_scan)
        schedule.every().day.at("16:05").do(self.send_daily_summary)

        self.run_scan()  # immediate first scan

        logger.info(f"Scanning every {config.SCAN_INTERVAL_MINUTES} min. Ctrl+C to stop.")
        try:
            while True:
                schedule.run_pending()
                time.sleep(30)
        except KeyboardInterrupt:
            logger.info("Stopping bot...")
            try:
                acct = self.alpaca.get_account()
            except Exception:
                acct = None
            self.telegram.send_stopped(self.scan_count, self.signal_count, acct)
            logger.info("Bot stopped.")


if __name__ == "__main__":
    engine = AlpharaghuEngine()
    engine.run()
