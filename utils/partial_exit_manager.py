"""
ALPHARAGHU - Partial Exit Manager
===================================
Advanced position management that goes beyond all-or-nothing exits.

Strategy:
  STEP 1 — Partial exit at 3×ATR profit
    Sell 50% of the position. Profit is locked. You cannot turn this
    winner into a full loser no matter what the second half does.

  STEP 2 — Trail the remaining 50% at 2×ATR
    The trailing stop ratchets UP as price rises, never down.
    Lets the second half run as far as it wants to go.

  STEP 3 — Time-based exit (dead trade protection)
    If a position is stuck within ±2% of entry for more than 10 days,
    sell everything. Dead money opportunity cost is real.

  STEP 4 — Volatility spike exit
    If the stock's current ATR has doubled since we entered, our
    original position sizing assumption is broken. Exit the chaos.

State persistence:
  All tracked positions are saved to data/partial_exits.json after
  every update. Survives bot restarts. On startup, existing positions
  are reloaded and monitoring resumes automatically.

Note: The GTC bracket orders placed at entry still live on Alpaca's
servers and will fire at the original stop/target. The partial exit
manager adds a SECOND layer of management on top of that.
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta

logger = logging.getLogger("alpharaghu.partial_exit")
ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(ROOT, "data", "partial_exits.json")

if "config" in sys.modules:
    config = sys.modules["config"]
else:
    import importlib.util
    spec = importlib.util.spec_from_file_location("config", os.path.join(ROOT, "config.py"))
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)


class PartialExitManager:
    """
    Manages partial exits and advanced trailing for all open positions.
    Wire into the main engine:
      - Call register(symbol, entry, qty, atr) right after a BUY order fills.
      - Call monitor(alpaca, telegram) at the start of every scan cycle.
    """

    def __init__(self):
        os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
        self._positions = {}   # symbol → position_dict
        self._load()

    # ── Persistence ───────────────────────────────────────────
    def _load(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE) as f:
                    data = json.load(f)
                self._positions = data.get("positions", {})
                if self._positions:
                    logger.info(
                        f"[PARTIAL] Resumed {len(self._positions)} tracked "
                        f"position(s) from disk: {list(self._positions.keys())}"
                    )
        except Exception as e:
            logger.error(f"[PARTIAL] Load error: {e}")
            self._positions = {}

    def _save(self):
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(
                    {"positions": self._positions,
                     "saved_at": datetime.now().isoformat()},
                    f, indent=2, default=str
                )
        except Exception as e:
            logger.error(f"[PARTIAL] Save error: {e}")

    # ── Registration ──────────────────────────────────────────
    def register(self, symbol: str, entry_price: float, qty: float, atr: float):
        """
        Call immediately after a BUY order is placed.
        Records the position for partial exit monitoring.
        """
        if not getattr(config, "USE_PARTIAL_EXITS", True):
            return

        mult_partial = getattr(config, "PARTIAL_EXIT_ATR_MULT", 3.0)
        mult_trail   = getattr(config, "PARTIAL_TRAIL_ATR_MULT",  2.0)

        self._positions[symbol] = {
            "entry":          round(entry_price, 4),
            "qty_original":   qty,
            "qty_remaining":  qty,
            "atr":            round(atr, 4),
            "partial_target": round(entry_price + atr * mult_partial, 2),
            "partial_filled": False,
            "trailing_stop":  None,      # Set after partial exit
            "registered_at":  datetime.now().isoformat(),
        }
        self._save()
        logger.info(
            f"[PARTIAL] Tracking {symbol}: "
            f"entry ${entry_price:.2f}  ATR ${atr:.2f}  "
            f"partial target ${self._positions[symbol]['partial_target']:.2f}  "
            f"qty {qty}"
        )

    def deregister(self, symbol: str):
        self._positions.pop(symbol, None)
        self._save()

    # ── Main monitor loop ─────────────────────────────────────
    def monitor(self, alpaca_client, telegram_bot=None):
        """
        Call at the start of every scan cycle.
        Checks each tracked position for exit conditions.
        """
        if not getattr(config, "USE_PARTIAL_EXITS", True):
            return
        if not self._positions:
            return

        # Sync with actual Alpaca positions — remove stale entries
        try:
            open_positions = alpaca_client.get_positions()
            open_symbols   = {p.symbol for p in open_positions}
            # Make a position dict for quick lookup
            pos_map = {p.symbol: p for p in open_positions}
        except Exception as e:
            logger.error(f"[PARTIAL] Could not fetch positions: {e}")
            return

        stale = [s for s in list(self._positions.keys()) if s not in open_symbols]
        for s in stale:
            logger.info(f"[PARTIAL] {s} no longer open — removing from tracker")
            self.deregister(s)

        for symbol, trade in list(self._positions.items()):
            try:
                self._check_position(symbol, trade, alpaca_client,
                                     pos_map, telegram_bot)
            except Exception as e:
                logger.error(f"[PARTIAL] Error checking {symbol}: {e}")

    def _check_position(self, symbol, trade, alpaca, pos_map, tg):
        """Run all exit checks for a single position."""

        # Get current price from Alpaca position object (no extra API call)
        p = pos_map.get(symbol)
        if p is None:
            return

        current = float(p.current_price)
        entry   = trade["entry"]
        atr     = trade["atr"]
        qty_rem = trade["qty_remaining"]
        pct     = (current - entry) / entry * 100

        mult_partial = getattr(config, "PARTIAL_EXIT_ATR_MULT", 3.0)
        mult_trail   = getattr(config, "PARTIAL_TRAIL_ATR_MULT",  2.0)

        # ── EXIT A: Time-based — stuck trade ─────────────────
        time_limit = getattr(config, "PARTIAL_TIME_EXIT_DAYS", 10)
        try:
            registered = datetime.fromisoformat(trade.get("registered_at", ""))
            hold_days  = (datetime.now() - registered).days
            if hold_days >= time_limit and abs(pct) < 2.0:
                logger.info(
                    f"  [PARTIAL] TIME EXIT: {symbol} stuck {hold_days}d at "
                    f"{pct:+.1f}% — selling remaining {qty_rem}"
                )
                alpaca.close_position(symbol)
                self._notify(tg, "time_exit", symbol, current, pct,
                             f"stuck {hold_days} days at breakeven")
                self.deregister(symbol)
                return
        except Exception:
            pass

        # ── EXIT B: Volatility spike ──────────────────────────
        if getattr(config, "PARTIAL_VOL_EXIT_ENABLED", True):
            try:
                current_atr = alpaca.get_atr(symbol)
                if current_atr > 0 and current_atr > atr * 2.0:
                    logger.info(
                        f"  [PARTIAL] VOL EXIT: {symbol} ATR spiked "
                        f"${atr:.2f}→${current_atr:.2f} (>2×) — "
                        f"selling remaining {qty_rem}"
                    )
                    alpaca.close_position(symbol)
                    self._notify(tg, "vol_exit", symbol, current, pct,
                                 f"ATR spiked 2× (${atr:.2f}→${current_atr:.2f})")
                    self.deregister(symbol)
                    return
            except Exception:
                pass

        # ── STEP 1: Partial exit at 3×ATR profit ─────────────
        if not trade["partial_filled"] and current >= trade["partial_target"]:
            half = max(1, int(trade["qty_original"] / 2))
            try:
                alpaca.place_market_order(
                    symbol=symbol,
                    qty=half,
                    side="sell",
                )
                trade["partial_filled"] = True
                trade["qty_remaining"]  = trade["qty_original"] - half
                trade["trailing_stop"]  = round(current - atr * mult_trail, 2)
                self._positions[symbol] = trade
                self._save()
                logger.info(
                    f"  [PARTIAL] 50% EXIT: Sold {half}x {symbol} @ ${current:.2f} "
                    f"(+{pct:.1f}%) | Trail set at ${trade['trailing_stop']:.2f}"
                )
                self._notify(tg, "partial", symbol, current, pct,
                             f"half sold at +{pct:.1f}% | trail ${trade['trailing_stop']:.2f}")
            except Exception as e:
                logger.error(f"  [PARTIAL] Partial exit error for {symbol}: {e}")
            return

        # ── STEP 2 + 3: Trail and check hit ──────────────────
        if trade["partial_filled"] and trade["trailing_stop"] is not None:
            new_trail = round(current - atr * mult_trail, 2)
            if new_trail > trade["trailing_stop"]:
                trade["trailing_stop"] = new_trail
                self._positions[symbol] = trade
                self._save()
                logger.info(
                    f"  [PARTIAL] TRAIL UP {symbol}: stop → "
                    f"${new_trail:.2f} (price ${current:.2f})"
                )

            if current <= trade["trailing_stop"]:
                try:
                    alpaca.close_position(symbol)
                    logger.info(
                        f"  [PARTIAL] TRAIL HIT: Sold remaining {qty_rem}x "
                        f"{symbol} @ ${current:.2f} | Trail was "
                        f"${trade['trailing_stop']:.2f}"
                    )
                    self._notify(tg, "trail_hit", symbol, current, pct,
                                 f"trailing stop hit at ${trade['trailing_stop']:.2f}")
                    self.deregister(symbol)
                except Exception as e:
                    logger.error(f"  [PARTIAL] Trail hit close error {symbol}: {e}")

    def _notify(self, tg, event: str, symbol: str, price: float,
                pct: float, detail: str):
        """Send a compact Telegram notification for exit events."""
        if tg is None:
            return
        try:
            emoji = {
                "partial":   "🎯",
                "trail_hit": "📈",
                "time_exit": "⏰",
                "vol_exit":  "⚡",
            }.get(event, "📤")
            label = {
                "partial":   "Partial Exit (50%)",
                "trail_hit": "Trail Stop Hit",
                "time_exit": "Time Exit",
                "vol_exit":  "Volatility Exit",
            }.get(event, "Exit")
            msg = (
                f"{emoji} <b>{label} — {symbol}</b>\n"
                f"${price:.2f}  ({pct:+.1f}%)\n"
                f"<i>{detail}</i>"
            )
            tg.send(msg)
        except Exception as e:
            logger.error(f"[PARTIAL] Telegram notify error: {e}")

    # ── Status ────────────────────────────────────────────────
    def get_tracked(self) -> dict:
        """Return copy of all tracked positions."""
        return dict(self._positions)

    def is_tracked(self, symbol: str) -> bool:
        return symbol in self._positions
