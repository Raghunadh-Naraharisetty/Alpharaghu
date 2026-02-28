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
        self.token      = config.TELEGRAM_BOT_TOKEN
        self.chat_id    = str(config.TELEGRAM_CHAT_ID)
        self.channel_id = str(getattr(config, "TELEGRAM_CHANNEL_ID", ""))
        self.enabled    = bool(self.token and self.chat_id and
                              self.token != "your_telegram_bot_token_here")
        self.channel_enabled = bool(self.enabled and self.channel_id)
        if not self.enabled:
            logger.warning("[TELEGRAM] Not configured - set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        if self.channel_enabled:
            logger.info(f"[TELEGRAM] Channel enabled: {self.channel_id}")
            # Send a test ping to confirm channel is working
            self.send_to_channel(
                f"<b>ALPHARAGHU Signals</b> — Bot Online\n"
                f"<i>Signals will be posted here when detected.</i>\n"
                f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M ET')}</i>"
            )

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

    def send_to_channel(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the public signals channel only."""
        if not self.channel_enabled:
            return False
        url     = self.BASE.format(token=self.token, method="sendMessage")
        payload = {
            "chat_id":                  self.channel_id,
            "text":                     text,
            "parse_mode":               parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                return True
            else:
                logger.error(f"Channel send error {r.status_code}: {r.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"Channel send failed: {e}")
            return False

    def send_both(self, text: str, parse_mode: str = "HTML"):
        """Send to both private chat AND channel."""
        self.send(text, parse_mode)
        self.send_to_channel(text, parse_mode)

    # ── Chart via sendPhoto ───────────────────────────────────
    def send_chart(self, symbol: str, png_bytes: bytes,
                   caption: str = "") -> bool:
        """
        Send a PNG chart image to private chat + channel via Telegram sendPhoto.
        No file storage required — sends raw bytes directly.
        """
        if not self.enabled or not png_bytes:
            return False
        sent = False
        targets_chat = [self.chat_id]
        if self.channel_enabled:
            targets_chat.append(self.channel_id)
        for chat_id in targets_chat:
            try:
                url  = self.BASE.format(token=self.token, method="sendPhoto")
                resp = requests.post(
                    url,
                    data={
                        "chat_id":    chat_id,
                        "caption":    caption[:1024],
                        "parse_mode": "HTML",
                    },
                    files={"photo": (f"{symbol}_chart.png", png_bytes, "image/png")},
                    timeout=20,
                )
                if resp.status_code == 200:
                    sent = True
                else:
                    logger.error(
                        f"[CHART] sendPhoto failed chat={chat_id}: "
                        f"{resp.status_code} {resp.text[:150]}"
                    )
            except Exception as e:
                logger.error(f"[CHART] sendPhoto error chat={chat_id}: {e}")
        return sent

    # ── Startup message ──────────────────────────────────────
    def send_startup(self, symbol_count: int, watchlist: list,
                     top_sectors: list = None) -> bool:
        now       = datetime.now().strftime("%H:%M")
        max_pos   = getattr(config, "MAX_OPEN_POSITIONS", 0)
        max_str   = "unlimited" if max_pos == 0 else str(max_pos)
        n_per_sec = getattr(config, "SECTOR_SCAN_TOP_N_PER_SECTOR", 8)
        n_sectors = len(top_sectors) if top_sectors else 3
        dyn_count = n_sectors * n_per_sec   # sector picks added on top of watchlist

        sector_line = ""
        if top_sectors:
            sector_line = f"\n📊 Top sectors: {' · '.join(top_sectors)}"
        else:
            sector_line = f"\n📊 Sector scan: loading…"

        msg = (
            f"🤖 <b>ALPHARAGHU online</b>  {now}\n"
            f"Scanning {symbol_count} watchlist + ~{dyn_count} sector picks "
            f"every {config.SCAN_INTERVAL_MINUTES}m"
            f"{sector_line}\n"
            f"Risk {config.RISK_PER_TRADE_PCT}%  |  Positions: {max_str}"
        )
        return self.send(msg)

    # ── Per-scan summary ─────────────────────────────────────
    def send_scan_summary(self, scan_num: int, checked: int, total: int,
                          signals: list, account=None,
                          scan_results: list = None,
                          positions: list = None) -> bool:
        """
        Minimal scan summary — quiet when nothing's happening,
        informative when there are signals or notable position moves.
        """
        now      = datetime.now().strftime("%H:%M")
        sig_buy  = [s for s in signals if s.get("signal") == "BUY"]
        sig_sell = [s for s in signals if s.get("signal") == "SELL"]

        lines = []

        # ── Signals (always show if present) ──────────────────
        for s in sig_buy:
            t   = s.get("targets", {})
            ep  = f"${t['entry']}" if t.get("entry") else "mkt"
            sl  = f"${t['stop']}"  if t.get("stop")  else "—"
            tp  = f"${t['target']}"if t.get("target") else "—"
            lines.append(
                f"📈 <b>BUY {s['symbol']}</b>  {s.get('confidence',0):.0%}\n"
                f"   EP {ep}  SL {sl}  TP {tp}"
            )

        for s in sig_sell:
            lines.append(
                f"📉 <b>SELL {s['symbol']}</b>  {s.get('confidence',0):.0%}"
            )

        # ── Near signals (watching list) ──────────────────────
        if scan_results and not signals:
            near = sorted(
                [r for r in scan_results if r.get("signal") == "HOLD"
                 and max(r.get("buy_confidence",0), r.get("sell_confidence",0)) > 0.38],
                key=lambda x: max(x.get("buy_confidence",0), x.get("sell_confidence",0)),
                reverse=True
            )[:3]
            if near:
                watching = "  ".join(
                    f"{r['symbol']} {max(r.get('buy_confidence',0),r.get('sell_confidence',0)):.0%}"
                    for r in near
                )
                lines.append(f"👀 Watching: {watching}")

        # ── Portfolio one-liner ────────────────────────────────
        if account:
            try:
                pl     = float(account.equity) - float(account.last_equity)
                port   = float(account.portfolio_value)
                n_pos  = len(positions) if positions is not None else "?"
                sign   = "+" if pl >= 0 else ""
                lines.append(
                    f"💼 ${port:,.0f}  Day {sign}${pl:,.0f}  {n_pos} pos"
                )
            except Exception:
                pass

        # ── Positions — only show if P&L is notable (>$5 move) ──
        if positions:
            notable = [
                p for p in positions
                if abs(float(p.unrealized_pl)) > 5
            ]
            if notable:
                pos_parts = []
                for p in notable:
                    pl   = float(p.unrealized_pl)
                    plpc = float(p.unrealized_plpc) * 100
                    pos_parts.append(f"{p.symbol} {plpc:+.1f}%")
                lines.append("   " + "  ".join(pos_parts))

        # ── Footer — quiet scan (no noise if nothing happened) ──
        if not lines:
            # Completely silent scan — just a tiny heartbeat every 4 scans
            if scan_num % 4 == 0:
                lines.append(f"· #{scan_num}  {now}  scanning {checked} symbols")
            else:
                return True  # Send nothing — truly silent

        # Prepend scan number if we have real content
        if lines and (signals or (scan_results and any(
            max(r.get("buy_confidence",0),r.get("sell_confidence",0)) > 0.38
            for r in (scan_results or []) if r.get("signal") == "HOLD"
        ))):
            lines.insert(0, f"<b>Scan #{scan_num}</b>  {now}")

        msg = "\n".join(lines)
        self.send(msg)  # always goes to private chat

        # ── Push signals to channel too (SELL signals are often missed) ──
        if signals:
            channel_lines = []
            for s in sig_buy:
                t  = s.get("targets", {})
                ep = f"${t['entry']}" if t.get("entry") else "mkt"
                sl = f"${t['stop']}"  if t.get("stop")  else "—"
                tp = f"${t['target']}"if t.get("target") else "—"
                channel_lines.append(
                    f"📈 <b>BUY {s['symbol']}</b>  {s.get('confidence',0):.0%}\n"
                    f"   EP {ep}  SL {sl}  TP {tp}"
                )
            for s in sig_sell:
                channel_lines.append(
                    f"📉 <b>SELL {s['symbol']}</b>  {s.get('confidence',0):.0%}\n"
                    f"   <i>Signal detected — pending MTF/filter check</i>"
                )
            if channel_lines:
                channel_lines.insert(0, f"<b>Scan #{scan_num}</b>  {now}")
                self.send_to_channel("\n".join(channel_lines))

        return True

    # ── Trade signal ─────────────────────────────────────────
    def send_signal(self, result: dict) -> bool:
        symbol    = result.get("symbol", "???")
        signal    = result.get("signal", "HOLD")
        conf      = result.get("confidence", 0)
        consensus = result.get("consensus", 0)
        if signal not in ("BUY", "SELL"):
            return False

        emoji   = "📈" if signal == "BUY" else "📉"
        targets = result.get("targets", {})
        t_line  = ""
        if targets:
            t_line = (
                f"\nEP <code>${targets.get('entry','?')}</code>  "
                f"SL <code>${targets.get('stop','?')}</code>  "
                f"TP <code>${targets.get('target','?')}</code>"
            )

        # Reason — one short line from each strategy that fired
        reasons = result.get("reason_lines", [])
        reason_line = " · ".join(r.split("|")[0].strip() for r in reasons[:2]) if reasons else ""

        msg = (
            f"{emoji} <b>{signal} {symbol}</b>  {conf:.0%}  {consensus}/3"
            f"{t_line}"
            + (f"\n<i>{reason_line}</i>" if reason_line else "")
        )
        self.send(msg)
        self.send_to_channel(msg)

        # ── Auto-chart on BUY ─────────────────────────────────
        if signal == "BUY" and targets:
            self._send_signal_chart(result, symbol, targets, conf, consensus)

        return True

    def _send_signal_chart(self, result, symbol, targets, conf, consensus):
        """Generate and send a candlestick chart for a BUY signal."""
        try:
            # Import chart generator
            import importlib.util
            cg_path = os.path.join(ROOT, "utils", "chart_generator.py")
            if not os.path.exists(cg_path):
                return
            spec = importlib.util.spec_from_file_location("chart_generator", cg_path)
            cg   = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cg)

            # Get bars via AlpacaClient (already imported in main.py)
            # We reach into sys.modules to avoid circular imports
            alpaca_mod = None
            for mod_name, mod in sys.modules.items():
                if hasattr(mod, "AlpacaClient"):
                    alpaca_mod = mod
                    break
            if alpaca_mod is None:
                logger.debug("[CHART] AlpacaClient not in sys.modules yet")
                return

            # Find the live alpaca instance via the engine
            alpaca_client = None
            for mod_name, mod in sys.modules.items():
                if hasattr(mod, "_alpaca_instance"):
                    alpaca_client = mod._alpaca_instance
                    break

            # Fallback: look for any object with get_bars
            if alpaca_client is None:
                for mod_name, mod in sys.modules.items():
                    obj = getattr(mod, "alpaca_client", None) or getattr(mod, "alpaca", None)
                    if obj and hasattr(obj, "get_bars"):
                        alpaca_client = obj
                        break

            if alpaca_client is None:
                logger.debug("[CHART] Could not find alpaca_client for charting")
                return

            # Fetch 5-min bars for the full session (~78 bars = 6.5 hrs)
            df = alpaca_client.get_bars(symbol, timeframe="5Min", limit=78)
            if df is None or (hasattr(df, "empty") and df.empty):
                return

            # Convert DataFrame to list of dicts
            bars = []
            for idx, row in df.iterrows():
                bars.append({
                    "timestamp": str(idx),
                    "open":   float(row["open"]),
                    "high":   float(row["high"]),
                    "low":    float(row["low"]),
                    "close":  float(row["close"]),
                    "volume": float(row.get("volume", 0)),
                })

            png = cg.generate_chart(
                symbol      = symbol,
                bars        = bars,
                entry       = float(targets.get("entry", 0)),
                stop        = float(targets.get("stop",  0)),
                target      = float(targets.get("target", 0)),
                confidence  = conf,
                consensus   = consensus,
                signal_time = datetime.now().strftime("%H:%M ET"),
            )

            if png:
                caption = (
                    f"📈 <b>BUY {symbol}</b>  {conf:.0%}  {consensus}/3\n"
                    f"EP <code>${targets.get('entry','??')}</code>  "
                    f"SL <code>${targets.get('stop','??')}</code>  "
                    f"TP <code>${targets.get('target','??')}</code>"
                )
                self.send_chart(symbol, png, caption)
                logger.info(f"[CHART] Sent chart for {symbol}")

        except Exception as e:
            logger.error(f"[CHART] Chart pipeline error for {symbol}: {e}")

    # ── Order filled ─────────────────────────────────────────
    def send_order_fill(self, symbol: str, side: str, qty: float, price: float) -> bool:
        emoji  = "✅" if side == "buy" else "🔴"
        action = "BOUGHT" if side == "buy" else "SOLD"
        msg = (
            f"{emoji} <b>{action} {symbol}</b>\n"
            f"{qty:.0f} sh @ <code>${price:.2f}</code>  "
            f"= <code>${qty * price:,.0f}</code>"
        )
        self.send_both(msg)
        return True

    # ── Stopped message ──────────────────────────────────────
    def send_stopped(self, scan_count: int, signal_count: int, account=None) -> bool:
        port = ""
        if account:
            try:
                port = f"  ${float(account.portfolio_value):,.0f}"
            except Exception:
                pass
        msg = f"⏹ <b>Bot stopped</b>{port}  #{scan_count} scans  {signal_count} signals"
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
