"""
ALPHARAGHU - Telegram Signal Bot
Sends formatted trading signals to your Telegram group
"""
import logging
import asyncio
import aiohttp
from datetime import datetime
from typing import Optional
import config

logger = logging.getLogger("alpharaghu.telegram")


class TelegramBot:
    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self):
        self.token   = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self._enabled = bool(self.token and self.chat_id)
        if not self._enabled:
            logger.warning("[WARN] Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")

    # ── Core Send ────────────────────────────────────────────
    async def _send_async(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self._enabled:
            logger.info(f"[TELEGRAM DISABLED] Would send:\n{text}")
            return False
        url = self.BASE_URL.format(token=self.token, method="sendMessage")
        payload = {
            "chat_id":    self.chat_id,
            "text":       text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return True
                    else:
                        body = await resp.text()
                        logger.error(f"Telegram error {resp.status}: {body}")
                        return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send(self, text: str) -> bool:
        """Synchronous wrapper for sending messages"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule the coroutine
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self._send_async(text))
                    return future.result(timeout=15)
            else:
                return loop.run_until_complete(self._send_async(text))
        except Exception as e:
            logger.error(f"Send error: {e}")
            return False

    # ── Signal Messages ──────────────────────────────────────
    def send_signal(self, signal_data: dict) -> bool:
        """
        Send a formatted trading signal message.
        signal_data from StrategyCombiner.run()
        """
        symbol    = signal_data.get("symbol", "???")
        signal    = signal_data.get("signal", "HOLD")
        conf      = signal_data.get("confidence", 0)
        consensus = signal_data.get("consensus", 0)
        ts        = datetime.now().strftime("%Y-%m-%d %H:%M ET")

        if signal == "BUY":
            emoji   = "🚀 BUY SIGNAL"
            color   = "🟢"
        elif signal == "SELL":
            emoji   = "🔴 SELL SIGNAL"
            color   = "🔴"
        else:
            return False  # Don't send HOLD signals

        # Strategy breakdown
        strat_lines = signal_data.get("reason_lines", [])
        strat_text  = "\n".join(f"  {line}" for line in strat_lines)

        # Entry/exit levels
        targets = signal_data.get("targets", {})
        target_text = ""
        if targets:
            entry  = targets.get("entry",  "—")
            sl     = targets.get("stop",   "—")
            tp     = targets.get("target", "—")
            target_text = (
                f"\n\n📌 <b>Levels</b>\n"
                f"  Entry:        <code>${entry}</code>\n"
                f"  Stop Loss:    <code>${sl}</code>\n"
                f"  Take Profit:  <code>${tp}</code>"
            )

        msg = (
            f"╔══════════════════════════╗\n"
            f"  {emoji}  {color}\n"
            f"╚══════════════════════════╝\n\n"
            f"📊 <b>{symbol}</b>\n"
            f"🕐 {ts}\n"
            f"🎯 Confidence: <b>{conf:.0%}</b>  |  {consensus}/3 strategies agree\n"
            f"{target_text}\n\n"
            f"<b>Strategy Breakdown:</b>\n"
            f"{strat_text}\n\n"
            f"#alpharaghu #{symbol} #{signal.lower()}"
        )
        return self.send(msg)

    def send_order_fill(self, symbol: str, side: str, qty: float,
                        price: float, order_id: str) -> bool:
        emoji = "✅ ORDER FILLED"
        side_txt = "BOUGHT" if side == "buy" else "SOLD"
        msg = (
            f"{emoji}\n\n"
            f"💼 <b>{side_txt} {symbol}</b>\n"
            f"Qty:   {qty} shares\n"
            f"Price: <code>${price:.2f}</code>\n"
            f"Total: <code>${qty * price:,.2f}</code>\n"
            f"Order: <code>{order_id}</code>\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S ET')}"
        )
        return self.send(msg)

    def send_portfolio_summary(self, account: object, positions: list) -> bool:
        equity    = float(account.equity)
        cash      = float(account.cash)
        pl        = float(account.equity) - float(account.last_equity)
        pl_pct    = (pl / float(account.last_equity)) * 100 if float(account.last_equity) else 0
        pl_emoji  = "📈" if pl >= 0 else "📉"

        pos_lines = ""
        for p in positions:
            p_pl  = float(p.unrealized_pl)
            p_pct = float(p.unrealized_plpc) * 100
            e     = "🟢" if p_pl >= 0 else "🔴"
            pos_lines += (
                f"  {e} <b>{p.symbol}</b>: {p.qty} shares "
                f"@ ${float(p.avg_entry_price):.2f} "
                f"| P&L: ${p_pl:+.2f} ({p_pct:+.1f}%)\n"
            )

        msg = (
            f"📊 <b>ALPHARAGHU Daily Summary</b>\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M ET')}\n\n"
            f"💰 Portfolio Value: <code>${equity:,.2f}</code>\n"
            f"💵 Cash Available:  <code>${cash:,.2f}</code>\n"
            f"{pl_emoji} Day P&L:         <code>${pl:+,.2f} ({pl_pct:+.2f}%)</code>\n\n"
            f"<b>Open Positions ({len(positions)}):</b>\n"
            f"{pos_lines if pos_lines else '  None\n'}\n"
            f"#alpharaghu #daily"
        )
        return self.send(msg)

    def send_startup_message(self) -> bool:
        msg = (
            f"🤖 <b>ALPHARAGHU Bot Started</b>\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M ET')}\n\n"
            f"✅ Alpaca: Connected\n"
            f"📡 Strategies: Momentum | Mean Reversion | News Sentiment\n"
            f"🔍 Scanner: Active\n"
            f"⚡ Status: Watching markets...\n\n"
            f"#alpharaghu #started"
        )
        return self.send(msg)

    def send_error(self, error_msg: str) -> bool:
        msg = f"⚠️ <b>ALPHARAGHU Error</b>\n\n<code>{error_msg[:300]}</code>"
        return self.send(msg)


# ─────────────────────────────────────────────────────────────
# MOBILE CONTROL - Telegram Command Handler
# Add this to your bot to control it from your phone!
#
# Setup:
#   1. Open Telegram, message @BotFather
#   2. Send /setcommands to your bot
#   3. Paste:
#        start - Start the trading bot
#        stop - Stop the trading bot
#        status - Get current bot status & portfolio
#        positions - List open positions
#        help - Show available commands
# ─────────────────────────────────────────────────────────────

import threading
import json
import os

class TelegramCommandHandler:
    """
    Polls Telegram for commands from your phone and acts on them.
    Run this in a background thread alongside the main engine.
    """

    COMMANDS = {
        "/start":     "Start the trading bot",
        "/stop":      "Stop the trading bot",
        "/status":    "Show portfolio & bot status",
        "/positions": "Show open positions",
        "/help":      "Show available commands",
    }

    def __init__(self, bot: TelegramBot, engine_ref=None):
        self.bot        = bot
        self.engine     = engine_ref
        self._offset    = 0
        self._running   = True
        self.state_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "logs", "bot_state.json"
        )

    def get_updates(self):
        import requests
        url = f"https://api.telegram.org/bot{self.bot.token}/getUpdates"
        try:
            resp = requests.get(url, params={"offset": self._offset, "timeout": 20}, timeout=25)
            if resp.status_code == 200:
                return resp.json().get("result", [])
        except Exception:
            pass
        return []

    def handle_command(self, text: str, chat_id: str):
        text = text.strip().lower().split()[0]  # Get just the command

        if text == "/start":
            self._set_state(True)
            self.bot.send("Bot STARTED. Scanning for signals every 15 min during market hours.")

        elif text == "/stop":
            self._set_state(False)
            self.bot.send("Bot STOPPED. Send /start to resume.")

        elif text == "/status":
            state = self._get_state()
            status = "RUNNING" if state.get("running") else "STOPPED"
            since  = state.get("started_at", "N/A")
            msg = (
                f"<b>ALPHARAGHU Status</b>\n\n"
                f"Bot: <b>{status}</b>\n"
                f"Since: {since}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M ET')}"
            )
            self.bot.send(msg)

        elif text == "/positions":
            try:
                if self.engine and hasattr(self.engine, 'alpaca'):
                    positions = self.engine.alpaca.get_positions()
                    if not positions:
                        self.bot.send("No open positions.")
                    else:
                        lines = ["<b>Open Positions:</b>\n"]
                        for p in positions:
                            pl = float(p.unrealized_pl)
                            lines.append(
                                f"  {p.symbol}: {p.qty} shares | "
                                f"P&L: ${pl:+.2f} ({float(p.unrealized_plpc)*100:+.1f}%)"
                            )
                        self.bot.send("\n".join(lines))
                else:
                    self.bot.send("Engine not available for position data.")
            except Exception as e:
                self.bot.send(f"Error getting positions: {e}")

        elif text == "/help":
            lines = ["<b>ALPHARAGHU Commands:</b>\n"]
            for cmd, desc in self.COMMANDS.items():
                lines.append(f"  {cmd} - {desc}")
            self.bot.send("\n".join(lines))

        else:
            self.bot.send(f"Unknown command: {text}\nSend /help for options.")

    def _set_state(self, running: bool):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        state = {"running": running, "started_at": datetime.now().isoformat() if running else None}
        with open(self.state_file, "w") as f:
            json.dump(state, f)

    def _get_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file) as f:
                    return json.load(f)
        except Exception:
            pass
        return {"running": False}

    def is_bot_running(self) -> bool:
        return self._get_state().get("running", True)

    def poll(self):
        """Run in background thread — polls Telegram for commands"""
        logger = logging.getLogger("alpharaghu.telegram.commands")
        logger.info("Telegram command handler started. Control bot from your phone!")
        while self._running:
            try:
                updates = self.get_updates()
                for update in updates:
                    self._offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    chat = str(msg.get("chat", {}).get("id", ""))
                    if text.startswith("/"):
                        logger.info(f"Command received: {text} from {chat}")
                        self.handle_command(text, chat)
            except Exception as e:
                logger.error(f"Poll error: {e}")
            import time as _time
            _time.sleep(2)

    def start_background(self):
        """Launch polling in a daemon thread"""
        t = threading.Thread(target=self.poll, daemon=True)
        t.start()
        return t
