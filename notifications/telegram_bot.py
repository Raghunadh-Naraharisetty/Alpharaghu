"""
ALPHARAGHU - Telegram Bot
Fixed commands + rich scan notifications
"""
import logging
import threading
import requests
import json
import os
import time
from datetime import datetime

logger = logging.getLogger("alpharaghu.telegram")

# ── Load config safely ───────────────────────────────────────
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if "config" in sys.modules:
    config = sys.modules["config"]
else:
    import importlib.util
    spec = importlib.util.spec_from_file_location("config", os.path.join(ROOT, "config.py"))
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)


class TelegramBot:
    BASE = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self):
        self.token   = config.TELEGRAM_BOT_TOKEN
        self.chat_id = str(config.TELEGRAM_CHAT_ID)
        self.enabled = bool(self.token and self.chat_id and
                           self.token != "your_telegram_bot_token_here")
        if not self.enabled:
            logger.warning("[TELEGRAM] Not configured - set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")

    # ── Core send ────────────────────────────────────────────
    def send(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.enabled:
            logger.info(f"[TELEGRAM DISABLED] {text[:80]}")
            return False
        url     = self.BASE.format(token=self.token, method="sendMessage")
        payload = {
            "chat_id":                  self.chat_id,
            "text":                     text,
            "parse_mode":               parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                return True
            else:
                logger.error(f"Telegram error {r.status_code}: {r.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    # ── Startup message ──────────────────────────────────────
    def send_startup(self, symbol_count: int, watchlist: list) -> bool:
        now = datetime.now().strftime("%H:%M:%S")
        dynamic_extra = 15 if getattr(config, "USE_DYNAMIC_SCANNER", True) else 0
        total_symbols = symbol_count + dynamic_extra
        scanner_note  = (
            f"{symbol_count} watchlist + ~{dynamic_extra} top movers (dynamic)"
            if dynamic_extra else f"{symbol_count} watchlist only"
        )
        msg = (
            f"<b>ALPHARAGHU Bot Started</b>\n\n"
            f"Interval: {config.SCAN_INTERVAL_MINUTES}m\n"
            f"Watching: ~{total_symbols} symbols\n"
            f"  ({scanner_note})\n\n"
            f"<b>Strategy 1 - Momentum:</b>\n"
            f"  EMA50, EMA200, RSI(14), MACD(12/26/9), Volume\n\n"
            f"<b>Strategy 2 - Mean Reversion:</b>\n"
            f"  Bollinger Bands(20), Stochastic(14/3), ATR(14)\n\n"
            f"<b>Strategy 3 - News Sentiment:</b>\n"
            f"  Alpaca News, Earnings Growth, Revenue Growth\n\n"
            f"Consensus: 2/3 strategies must agree\n"
            f"News filter: ON\n"
            f"Earnings guard: ON\n"
            f"Risk/trade: {config.RISK_PER_TRADE_PCT}% | "
            f"Stop: {config.STOP_LOSS_PCT}% | "
            f"Target: {config.TAKE_PROFIT_PCT}%\n"
            f"Max positions: {config.MAX_OPEN_POSITIONS}\n"
            f"Time: {now}\n\n"
            f"<i>Scan summary sent every {config.SCAN_INTERVAL_MINUTES}m</i>"
        )
        return self.send(msg)

    # ── Per-scan summary ─────────────────────────────────────
    def send_scan_summary(self, scan_num: int, checked: int, total: int,
                          signals: list, account=None,
                          scan_results: list = None) -> bool:
        """
        Sends a rich per-scan summary to Telegram.
        scan_results: list of all symbol results (not just signals)
        """
        now     = datetime.now().strftime("%H:%M:%S")
        sig_buy  = [s for s in signals if s.get("signal") == "BUY"]
        sig_sell = [s for s in signals if s.get("signal") == "SELL"]

        # ── Header ───────────────────────────────────────────
        lines = [
            f"<b>Scan #{scan_num}</b>   {now}",
            f"",
            f"Checked: {checked}/{total} symbols",
            f"Signals: {len(signals)}  "
            f"(BUY: {len(sig_buy)}  SELL: {len(sig_sell)})",
        ]

        # ── BUY signals ───────────────────────────────────────
        if sig_buy:
            lines.append("")
            lines.append("<b>BUY Signals:</b>")
            for s in sig_buy:
                conf = s.get("confidence", 0)
                cons = s.get("consensus", 0)
                t    = s.get("targets", {})
                entry  = t.get("entry",  "?")
                stop   = t.get("stop",   "?")
                target = t.get("target", "?")
                lines.append(
                    f"  BUY <b>{s['symbol']}</b> "
                    f"| {conf:.0%} conf | {cons}/3"
                )
                if entry != "?":
                    lines.append(
                        f"    Entry: ${entry}  Stop: ${stop}  TP: ${target}"
                    )

        # ── SELL signals ──────────────────────────────────────
        if sig_sell:
            lines.append("")
            lines.append("<b>SELL Signals:</b>")
            for s in sig_sell:
                conf = s.get("confidence", 0)
                cons = s.get("consensus", 0)
                lines.append(
                    f"  SELL <b>{s['symbol']}</b> "
                    f"| {conf:.0%} conf | {cons}/3"
                )

        # ── No signals ────────────────────────────────────────
        if not signals:
            lines.append("")
            lines.append("No signals this scan")

        # ── Top movers watched (from scan_results) ────────────
        if scan_results:
            # Show top 5 by absolute confidence (closest to triggering)
            near_signals = sorted(
                [r for r in scan_results if r.get("signal") == "HOLD"
                 and max(r.get("buy_confidence", 0), r.get("sell_confidence", 0)) > 0.35],
                key=lambda x: max(x.get("buy_confidence", 0), x.get("sell_confidence", 0)),
                reverse=True
            )[:5]
            if near_signals:
                lines.append("")
                lines.append("<b>Near Signals (watching):</b>")
                for r in near_signals:
                    bc  = r.get("buy_confidence",  0)
                    sc  = r.get("sell_confidence", 0)
                    if bc >= sc:
                        direction = f"BUY  {bc:.0%}"
                    else:
                        direction = f"SELL {sc:.0%}"
                    lines.append(f"  {r['symbol']}: {direction}")

        # ── Portfolio ─────────────────────────────────────────
        if account:
            try:
                portfolio = float(account.portfolio_value)
                cash      = float(account.cash)
                equity    = float(account.equity)
                last_eq   = float(account.last_equity)
                pl        = equity - last_eq
                pl_pct    = (pl / last_eq * 100) if last_eq else 0
                pl_sign   = "+" if pl >= 0 else ""
                lines += [
                    "",
                    f"Portfolio: <b>${portfolio:,.2f}</b>",
                    f"Cash: ${cash:,.2f}",
                    f"Day P&amp;L: ${pl_sign}{pl:,.2f} ({pl_sign}{pl_pct:.2f}%)",
                ]
            except Exception:
                pass

        # ── Footer ────────────────────────────────────────────
        lines.append("")
        lines.append(f"<i>Next scan in {config.SCAN_INTERVAL_MINUTES}m</i>")

        return self.send("\n".join(lines))

    # ── Trade signal ─────────────────────────────────────────
    def send_signal(self, result: dict) -> bool:
        symbol    = result.get("symbol", "???")
        signal    = result.get("signal", "HOLD")
        conf      = result.get("confidence", 0)
        consensus = result.get("consensus", 0)
        if signal not in ("BUY", "SELL"):
            return False

        direction = "BUY SIGNAL" if signal == "BUY" else "SELL SIGNAL"
        strat_lines = result.get("reason_lines", [])
        strat_text  = "\n".join(f"  {l}" for l in strat_lines)

        targets = result.get("targets", {})
        t_text  = ""
        if targets:
            t_text = (
                f"\nEntry:       <code>${targets.get('entry','?')}</code>\n"
                f"Stop Loss:   <code>${targets.get('stop','?')}</code>\n"
                f"Take Profit: <code>${targets.get('target','?')}</code>"
            )

        msg = (
            f"<b>{direction} — {symbol}</b>\n"
            f"Confidence: {conf:.0%} | {consensus}/3 strategies\n"
            f"{t_text}\n\n"
            f"<b>Breakdown:</b>\n{strat_text}\n\n"
            f"#{symbol.lower()} #{signal.lower()}"
        )
        return self.send(msg)

    # ── Order filled ─────────────────────────────────────────
    def send_order_fill(self, symbol: str, side: str, qty: float, price: float) -> bool:
        action = "BOUGHT" if side == "buy" else "SOLD"
        msg = (
            f"<b>Order Filled — {action} {symbol}</b>\n"
            f"Qty: {qty} shares\n"
            f"Price: <code>${price:.2f}</code>\n"
            f"Total: <code>${qty * price:,.2f}</code>\n"
            f"Time: {datetime.now().strftime('%H:%M:%S')}"
        )
        return self.send(msg)

    # ── Stopped message ──────────────────────────────────────
    def send_stopped(self, scan_count: int, signal_count: int, account=None) -> bool:
        portfolio = "N/A"
        positions = "N/A"
        if account:
            try:
                portfolio = f"${float(account.portfolio_value):,.2f}"
            except Exception:
                pass
        msg = (
            f"<b>Bot Stopped</b>\n\n"
            f"Scans: {scan_count}\n"
            f"Total signals: {signal_count}\n"
            f"Final portfolio: {portfolio}\n"
            f"Time: {datetime.now().strftime('%H:%M:%S')}"
        )
        return self.send(msg)

    # ── Portfolio summary ────────────────────────────────────
    def send_portfolio_summary(self, account, positions: list) -> bool:
        equity = float(account.equity)
        cash   = float(account.cash)
        pl     = equity - float(account.last_equity)
        pl_pct = (pl / float(account.last_equity)) * 100 if float(account.last_equity) else 0

        pos_lines = ""
        for p in positions:
            p_pl  = float(p.unrealized_pl)
            p_pct = float(p.unrealized_plpc) * 100
            pos_lines += (
                f"  <b>{p.symbol}</b>: {p.qty} shares @ ${float(p.avg_entry_price):.2f}"
                f" | P&amp;L: ${p_pl:+.2f} ({p_pct:+.1f}%)\n"
            )

        msg = (
            f"<b>ALPHARAGHU Daily Summary</b>\n"
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Portfolio: <b>${equity:,.2f}</b>\n"
            f"Cash: ${cash:,.2f}\n"
            f"Day P&amp;L: ${pl:+,.2f} ({pl_pct:+.2f}%)\n\n"
            f"<b>Positions ({len(positions)}):</b>\n"
            f"{pos_lines if pos_lines else 'None'}"
        )
        return self.send(msg)

    def send_error(self, msg: str) -> bool:
        return self.send(f"<b>Error</b>\n<code>{msg[:300]}</code>")

    # ── Legacy alias ─────────────────────────────────────────
    def send_startup_message(self):
        return self.send_startup(len(config.WATCHLIST), config.WATCHLIST)


# ─────────────────────────────────────────────────────────────
# TELEGRAM COMMAND HANDLER (Mobile control)
# ─────────────────────────────────────────────────────────────
class TelegramCommandHandler:

    COMMANDS = {
        "/start":     "Start the trading bot",
        "/stop":      "Stop the trading bot",
        "/status":    "Get portfolio and bot status",
        "/positions": "Show open positions",
        "/help":      "Show available commands",
    }

    def __init__(self, bot: TelegramBot, engine_ref=None):
        self.bot      = bot
        self.engine   = engine_ref
        self._offset  = 0
        self._running = True
        self.state_file = os.path.join(ROOT, "logs", "bot_state.json")
        os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)

    # ── State file ───────────────────────────────────────────
    def set_state(self, running: bool):
        state = {
            "running":    running,
            "started_at": datetime.now().isoformat() if running else None,
        }
        with open(self.state_file, "w") as f:
            json.dump(state, f)

    def get_state(self) -> dict:
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file) as f:
                    return json.load(f)
        except Exception:
            pass
        return {"running": True}

    def is_running(self) -> bool:
        return self.get_state().get("running", True)

    # ── Get updates from Telegram ────────────────────────────
    def get_updates(self) -> list:
        url = f"https://api.telegram.org/bot{self.bot.token}/getUpdates"
        try:
            r = requests.get(
                url,
                params={"offset": self._offset, "timeout": 10},
                timeout=15
            )
            if r.status_code == 200:
                return r.json().get("result", [])
        except Exception as e:
            logger.debug(f"getUpdates error: {e}")
        return []

    # ── Handle a command ────────────────────────────────────
    def handle(self, text: str):
        cmd = text.strip().split()[0].lower()
        # Handle /command@botname format
        if "@" in cmd:
            cmd = cmd.split("@")[0]

        logger.info(f"[CMD] Received: {cmd}")

        if cmd == "/start":
            self.set_state(True)
            self.bot.send(
                "<b>Bot STARTED</b>\n\n"
                "Scanning for signals every "
                f"{config.SCAN_INTERVAL_MINUTES} min during market hours.\n"
                "Send /stop to pause."
            )

        elif cmd == "/stop":
            self.set_state(False)
            self.bot.send(
                "<b>Bot STOPPED</b>\n\n"
                "No new trades will be placed.\n"
                "Send /start to resume."
            )

        elif cmd == "/status":
            state  = self.get_state()
            status = "RUNNING" if state.get("running") else "STOPPED"
            since  = (state.get("started_at") or "N/A")[:16].replace("T", " ")
            port   = "N/A"
            if self.engine and hasattr(self.engine, "alpaca"):
                try:
                    port = f"${self.engine.alpaca.get_portfolio_value():,.2f}"
                except Exception:
                    pass
            self.bot.send(
                f"<b>ALPHARAGHU Status</b>\n\n"
                f"Status: <b>{status}</b>\n"
                f"Since: {since}\n"
                f"Portfolio: {port}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )

        elif cmd == "/positions":
            if self.engine and hasattr(self.engine, "alpaca"):
                try:
                    positions = self.engine.alpaca.get_positions()
                    if not positions:
                        self.bot.send("No open positions.")
                    else:
                        lines = ["<b>Open Positions:</b>\n"]
                        for p in positions:
                            pl  = float(p.unrealized_pl)
                            pct = float(p.unrealized_plpc) * 100
                            lines.append(
                                f"<b>{p.symbol}</b>: {p.qty} @ ${float(p.avg_entry_price):.2f}"
                                f" | P&amp;L: ${pl:+.2f} ({pct:+.1f}%)"
                            )
                        self.bot.send("\n".join(lines))
                except Exception as e:
                    self.bot.send(f"Error: {e}")
            else:
                self.bot.send("Engine not available.")

        elif cmd == "/help":
            lines = ["<b>Available Commands:</b>\n"]
            for c, d in self.COMMANDS.items():
                lines.append(f"{c} - {d}")
            self.bot.send("\n".join(lines))

        else:
            self.bot.send(f"Unknown command: {cmd}\nSend /help for options.")

    # ── Background polling loop ───────────────────────────────
    def poll(self):
        logger.info("[CMD] Telegram command handler listening...")
        while self._running:
            try:
                updates = self.get_updates()
                for upd in updates:
                    self._offset = upd["update_id"] + 1
                    msg  = upd.get("message") or upd.get("edited_message", {})
                    text = msg.get("text", "")
                    if text.startswith("/"):
                        self.handle(text)
            except Exception as e:
                logger.error(f"Poll error: {e}")
            time.sleep(2)

    def start_background(self):
        t = threading.Thread(target=self.poll, daemon=True, name="TelegramCmdHandler")
        t.start()
        return t
