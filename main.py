"""
ALPHARAGHU - Main Trading Engine v2.0
New in this version:
  - Trailing stops (locks in profit)
  - Drawdown circuit breaker (emergency halt)
  - Daily loss limit
  - Trade cooldown
  - Multi-timeframe trend filter
  - SQLite trade history database
"""
import sys, os, importlib.util, logging, time, schedule, json
from datetime import datetime

os.environ["PYTHONUTF8"] = "1"
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)

# ── Logging ──────────────────────────────────────────────────
fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s - %(message)s")
ch  = logging.StreamHandler(sys.stdout); ch.setFormatter(fmt)
fh  = logging.FileHandler(os.path.join(ROOT, "logs", "alpharaghu.log"), encoding="utf-8")
fh.setFormatter(fmt)
logging.basicConfig(level=logging.INFO, handlers=[ch, fh])
logger = logging.getLogger("alpharaghu.engine")

# ── Module loader ─────────────────────────────────────────────
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
db_mod       = load("trade_db",      "utils",          "trade_database.py")
risk_mod     = load("risk_manager",  "utils",          "risk_manager.py")

AlpacaClient           = alpaca_mod.AlpacaClient
StrategyCombiner       = combiner_mod.StrategyCombiner
TelegramBot            = tg_mod.TelegramBot
TelegramCommandHandler = tg_mod.TelegramCommandHandler
NewsFetcher            = news_mod.NewsFetcher
TradeDatabase          = db_mod.TradeDatabase
RiskManager            = risk_mod.RiskManager
logger.info("All modules loaded OK")

# ── Helpers ───────────────────────────────────────────────────
SIGNAL_LOG = os.path.join(ROOT, "logs", "signals.json")
STATE_FILE  = os.path.join(ROOT, "logs", "bot_state.json")

def is_paused():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return not json.load(f).get("running", True)
    except Exception:
        pass
    return False

def log_signal_json(result):
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


# ── Engine ────────────────────────────────────────────────────
class AlpharaghuEngine:

    def __init__(self):
        logger.info("=" * 60)
        logger.info("  ALPHARAGHU v2.0 - Algo Trading Engine")
        logger.info("  + Trailing Stops | + Drawdown Breaker")
        logger.info("  + Trade Database | + MTF Trend Filter")
        logger.info("=" * 60)

        self.alpaca   = AlpacaClient()
        self.telegram = TelegramBot()
        self.combiner = StrategyCombiner()
        self.news     = NewsFetcher(alpaca_client=self.alpaca)
        self.db       = TradeDatabase()
        self.risk     = RiskManager(self.alpaca)

        self.scan_count   = 0
        self.signal_count = 0
        self.active_signals = {}

        # Telegram commands for mobile control
        self.cmd_handler = TelegramCommandHandler(self.telegram, engine_ref=self)
        self.cmd_handler.start_background()
        logger.info("[CMD] Telegram commands ready")

    # ── Symbol universe ───────────────────────────────────────
    def get_symbols(self):
        symbols = list(config.WATCHLIST)
        if config.USE_DYNAMIC_SCANNER:
            symbols = list(set(symbols + self.alpaca.get_top_movers(top_n=15)))
        return symbols

    # ── Main scan ─────────────────────────────────────────────
    def run_scan(self):
        if is_paused():
            logger.info("Bot paused — skipping scan")
            return
        if not self.alpaca.is_market_open():
            logger.info("Market closed — skipping scan")
            return

        # ── Safety checks BEFORE scanning ─────────────────────
        dd = self.risk.check_drawdown()
        if not dd["ok"]:
            logger.critical(f"[HALT] {dd['reason']}")
            self.telegram.send(
                f"<b>EMERGENCY HALT</b>\n\n"
                f"Drawdown: {dd['drawdown_pct']:.1f}%\n"
                f"All trading stopped. Review manually."
            )
            return

        dl = self.risk.check_daily_loss()
        if not dl["ok"]:
            logger.warning(f"[DAILY LIMIT] {dl['reason']}")
            self.telegram.send(f"<b>Daily Loss Limit Hit</b>\n{dl['reason']}\nNo new trades today.")
            return

        self.scan_count += 1
        symbols        = self.get_symbols()
        open_positions = self.alpaca.get_open_position_count()
        scan_signals   = []
        all_results    = []

        logger.info(f"--- Scan #{self.scan_count} | {len(symbols)} symbols ---")

        # ── Manage existing positions first (trailing stops) ───
        self._manage_positions()

        # ── Scan for new signals ───────────────────────────────
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

        # ── Telegram scan summary ──────────────────────────────
        try:
            acct      = self.alpaca.get_account()
            positions = self.alpaca.get_positions()

            # Snapshot to DB
            try:
                day_pnl = float(acct.equity) - float(acct.last_equity)
                self.db.snapshot_portfolio(
                    float(acct.portfolio_value), float(acct.cash),
                    len(positions), day_pnl
                )
            except Exception:
                pass

            self.telegram.send_scan_summary(
                scan_num=self.scan_count,
                checked=len(symbols),
                total=len(symbols),
                signals=scan_signals,
                account=acct,
                scan_results=all_results,
                positions=positions,
            )
        except Exception as e:
            logger.error(f"Scan summary error: {e}")

    # ── Manage open positions (trailing stops) ─────────────────
    def _manage_positions(self):
        positions = self.alpaca.get_positions()
        for p in positions:
            symbol       = p.symbol
            current_price = float(p.current_price)
            entry_price   = float(p.avg_entry_price)

            trail = self.risk.update_trailing_stop(symbol, current_price, entry_price)
            logger.debug(f"  [TRAIL] {symbol}: {trail['reason']}")

            if trail["action"] == "close":
                logger.info(f"  [TRAIL STOP] Closing {symbol} — {trail['reason']}")
                self.alpaca.close_position(symbol)
                self.risk.clear_trailing(symbol)
                self.telegram.send(
                    f"<b>Trailing Stop Hit — {symbol}</b>\n"
                    f"Closed at ${current_price:.2f}\n"
                    f"Reason: {trail['reason']}"
                )
                # Record in DB
                self.db.record_close(symbol, current_price, trail["reason"])

    # ── Analyze single symbol ──────────────────────────────────
    def _analyze_symbol(self, symbol, open_positions):
        df_15  = self.alpaca.get_bars(symbol, timeframe="15Min", limit=250)
        df_day = self.alpaca.get_bars(symbol, timeframe="1Day",  limit=252)

        if df_15.empty or len(df_15) < 50:
            return None

        news   = self.news.get_all_news(symbol)
        result = self.combiner.run(symbol, df_15, df_day, news)

        signal = result["signal"]
        conf   = result["confidence"]
        cons   = result["consensus"]
        bc     = result.get("buy_confidence",  0)
        sc     = result.get("sell_confidence", 0)

        if bc > 0.25 or sc > 0.25:
            logger.info(f"  {symbol}: {signal} | {conf:.0%} | {cons}/3 "
                       f"[B:{bc:.0%} S:{sc:.0%}]")
        else:
            logger.info(f"  {symbol}: {signal} | {conf:.0%} | {cons}/3")

        # Log signal to DB
        self.db.log_signal(symbol, signal, conf, cons,
                           " | ".join(result.get("reason_lines", [])),
                           acted=False)

        if signal == "HOLD":
            return result

        # Deduplicate within 30 min
        last = self.active_signals.get(symbol, {})
        if (last.get("signal") == signal and
                (datetime.now() - last.get("time", datetime(2000,1,1))).seconds < 1800):
            return result

        # ── Cooldown check ─────────────────────────────────────
        if not self.risk.check_cooldown(symbol):
            logger.info(f"  {symbol}: in cooldown — skipping")
            return result

        # ── MTF trend filter ───────────────────────────────────
        if getattr(config, "USE_MTF_FILTER", True):
            mtf = self.risk.check_trend_alignment(symbol, signal, self.alpaca)
            if not mtf["aligned"]:
                logger.info(f"  {symbol}: MTF filter blocked — {mtf['reason']}")
                return result
            logger.debug(f"  {symbol}: MTF OK — {mtf['reason']}")

        price = df_15["close"].iloc[-1]
        pos   = self.alpaca.get_position(symbol)

        if signal == "BUY" and not pos and open_positions < config.MAX_OPEN_POSITIONS:
            self._execute_buy(symbol, price, result)

        elif signal == "SELL" and pos:
            self._execute_sell(symbol, price, result, pos)

        log_signal_json(result)
        self.active_signals[symbol] = {"signal": signal, "time": datetime.now()}
        return result

    # ── Execute BUY ───────────────────────────────────────────
    def _execute_buy(self, symbol, price, result):

        # ── Correlation guard: VIX family ─────────────────────
        # VIXY and UVXY both track VIX — holding both = double exposure
        # If we already own one VIX ETF, skip buying another
        VIX_FAMILY = {"VIXY", "UVXY", "VXX", "SVXY"}
        if symbol in VIX_FAMILY:
            held_positions = self.alpaca.get_positions()
            held_symbols   = {p.symbol for p in held_positions}
            already_vix    = held_symbols & VIX_FAMILY
            if already_vix:
                logger.info(
                    f"  {symbol}: SKIPPED — already holding VIX ETF "
                    f"{already_vix} (correlation guard)"
                )
                return

        stop_price   = price * (1 - config.STOP_LOSS_PCT   / 100)
        target_price = price * (1 + config.TAKE_PROFIT_PCT / 100)
        qty          = self.alpaca.calculate_position_size(price, stop_price)

        if qty < 0.01:
            logger.warning(f"  {symbol}: position size too small")
            return

        order = self.alpaca.place_market_order(
            symbol=symbol, qty=qty, side="buy",
            stop_loss=stop_price, take_profit=target_price,
        )
        if order:
            result["targets"] = {
                "entry":  round(price, 2),
                "stop":   round(stop_price, 2),
                "target": round(target_price, 2),
            }
            # Record in trade DB
            self.db.record_open(
                trade_id=str(order.id), symbol=symbol, side="buy",
                qty=qty, entry_price=price,
                strategy="combined", confidence=result.get("confidence", 0)
            )
            self.risk.record_trade(symbol)
            logger.info(f"  [BUY FILLED] {qty:.2f}x {symbol} @ ~${price:.2f}")
            self.telegram.send_signal(result)

    # ── Execute SELL ──────────────────────────────────────────
    def _execute_sell(self, symbol, price, result, position):
        self.alpaca.close_position(symbol)
        self.risk.clear_trailing(symbol)
        try:
            pl = float(position.unrealized_pl)
            self.db.record_close(symbol, price, "signal_sell")
            logger.info(f"  [SELL FILLED] {symbol} | P&L: ${pl:+.2f}")
        except Exception:
            logger.info(f"  [SELL FILLED] {symbol}")
        self.telegram.send_signal(result)

    # ── Daily jobs ────────────────────────────────────────────
    def send_daily_summary(self):
        try:
            self.risk.reset_daily()   # Reset day start value
            acct  = self.alpaca.get_account()
            pos   = self.alpaca.get_positions()
            perf  = self.db.get_performance()
            self.telegram.send_portfolio_summary(acct, pos)

            # Also send performance stats if we have trades
            if perf.get("total_trades", 0) > 0:
                self.telegram.send(
                    f"<b>Performance Stats</b>\n\n"
                    f"Total Trades: {perf['total_trades']}\n"
                    f"Win Rate:     {perf['win_rate']}%\n"
                    f"Profit Factor: {perf['profit_factor']}\n"
                    f"Total P&amp;L:  ${perf['total_pnl']:+,.2f}\n"
                    f"Best Trade:   ${perf['best_trade']:+,.2f}\n"
                    f"Worst Trade:  ${perf['worst_trade']:+,.2f}"
                )
        except Exception as e:
            logger.error(f"Daily summary error: {e}")

    # ── Main loop ─────────────────────────────────────────────
    def run(self):
        logger.info("Engine starting...")
        symbols = self.get_symbols()
        self.telegram.send_startup(len(symbols), symbols)

        # Log existing positions
        positions = self.alpaca.get_positions()
        if positions:
            logger.info(f"  Found {len(positions)} existing position(s):")
            for p in positions:
                logger.info(f"    {p.symbol}: {p.qty} shares @ "
                           f"${float(p.avg_entry_price):.2f} | "
                           f"P&L: ${float(p.unrealized_pl):+.2f}")

        schedule.every(config.SCAN_INTERVAL_MINUTES).minutes.do(self.run_scan)
        schedule.every().day.at("09:31").do(self.risk.reset_daily)
        schedule.every().day.at("16:05").do(self.send_daily_summary)

        self.run_scan()  # Immediate first scan

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
