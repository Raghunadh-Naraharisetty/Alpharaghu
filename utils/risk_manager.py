"""
ALPHARAGHU - Risk Manager
Features borrowed from friend's system + enhanced:
  - Trailing stop loss
  - Drawdown circuit breaker
  - Daily loss limit
  - Trade cooldown
  - Multi-timeframe trend filter
"""
import logging, os, sys
from datetime import datetime, timedelta

logger = logging.getLogger("alpharaghu.risk")
ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if "config" in sys.modules:
    config = sys.modules["config"]
else:
    import importlib.util
    spec = importlib.util.spec_from_file_location("config", os.path.join(ROOT, "config.py"))
    config = importlib.util.module_from_spec(spec); spec.loader.exec_module(config)


class RiskManager:
    """
    Centralized risk management:
      1. Trailing stops        — locks in profit as price rises
      2. Drawdown breaker      — halts trading if portfolio drops X%
      3. Daily loss limit      — stops trading after losing Y% in one day
      4. Trade cooldown        — prevents re-entering same symbol too soon
      5. MTF trend filter      — only buy in direction of weekly/daily trend
    """

    def __init__(self, alpaca_client):
        self.client          = alpaca_client
        self.peak_value      = None
        self.day_start_value = None
        self.last_trade_time = {}          # symbol → datetime
        self.trailing_stops  = {}          # symbol → current trailing stop price
        self.halted          = False       # emergency halt flag
        self._init()

    def _init(self):
        try:
            val = self.client.get_portfolio_value()
            self.peak_value      = val
            self.day_start_value = val
            logger.info(f"[RISK] Initialized | Portfolio: ${val:,.2f}")
        except Exception as e:
            logger.error(f"[RISK] Init error: {e}")

    # ── 1. TRAILING STOP ─────────────────────────────────────
    def update_trailing_stop(self, symbol: str, current_price: float,
                              entry_price: float) -> dict:
        """
        Updates trailing stop for a position.
        Returns: { "action": "hold"|"close", "stop_price": float, "reason": str }
        """
        pnl_pct = (current_price - entry_price) / entry_price * 100

        # Only activate trailing stop after TRAILING_ACTIVATION_PCT profit
        activation = getattr(config, "TRAILING_STOP_ACTIVATION_PCT", 2.0)
        trail_dist  = getattr(config, "TRAILING_STOP_DISTANCE_PCT",  1.0)

        if pnl_pct < activation:
            # Not yet in profit enough to trail — use regular stop
            regular_stop = entry_price * (1 - config.STOP_LOSS_PCT / 100)
            if current_price <= regular_stop:
                return {
                    "action": "close",
                    "stop_price": regular_stop,
                    "reason": f"stop_loss ({pnl_pct:+.1f}%)"
                }
            return {"action": "hold", "stop_price": regular_stop, "reason": "below activation"}

        # Trailing stop active
        new_trail = current_price * (1 - trail_dist / 100)
        old_trail  = self.trailing_stops.get(symbol, entry_price * (1 - config.STOP_LOSS_PCT / 100))
        trail_stop = max(new_trail, old_trail)   # Only move UP, never down
        self.trailing_stops[symbol] = trail_stop

        if current_price <= trail_stop:
            del self.trailing_stops[symbol]
            return {
                "action": "close",
                "stop_price": trail_stop,
                "reason": f"trailing_stop ({pnl_pct:+.1f}% profit locked)"
            }

        return {
            "action":     "hold",
            "stop_price": trail_stop,
            "reason":     f"trailing at ${trail_stop:.2f} | profit: {pnl_pct:+.1f}%"
        }

    # ── 2. DRAWDOWN CIRCUIT BREAKER ──────────────────────────
    def check_drawdown(self) -> dict:
        """
        Returns: { "ok": bool, "drawdown_pct": float, "reason": str }
        Halts all trading if max drawdown exceeded.
        """
        if self.halted:
            return {"ok": False, "drawdown_pct": 0, "reason": "Bot halted (drawdown limit hit)"}

        try:
            current = self.client.get_portfolio_value()
            if current > self.peak_value:
                self.peak_value = current   # Update peak

            drawdown_pct = (self.peak_value - current) / self.peak_value * 100
            max_dd       = getattr(config, "MAX_DRAWDOWN_PCT", 10.0)

            if drawdown_pct >= max_dd:
                self.halted = True
                logger.critical(
                    f"[RISK] EMERGENCY HALT! Drawdown {drawdown_pct:.1f}% "
                    f"exceeds limit {max_dd}%"
                )
                return {
                    "ok": False,
                    "drawdown_pct": round(drawdown_pct, 2),
                    "reason": f"Max drawdown {max_dd}% exceeded ({drawdown_pct:.1f}%)"
                }
            return {"ok": True, "drawdown_pct": round(drawdown_pct, 2), "reason": "OK"}
        except Exception as e:
            logger.error(f"[RISK] Drawdown check error: {e}")
            return {"ok": True, "drawdown_pct": 0, "reason": "check error — allowing trade"}

    # ── 3. DAILY LOSS LIMIT ───────────────────────────────────
    def check_daily_loss(self) -> dict:
        """Stop trading if day loss exceeds MAX_DAILY_LOSS_PCT"""
        try:
            current   = self.client.get_portfolio_value()
            daily_pnl = current - self.day_start_value
            daily_pct = (daily_pnl / self.day_start_value) * 100
            max_loss  = -abs(getattr(config, "MAX_DAILY_LOSS_PCT", 5.0))

            if daily_pct <= max_loss:
                logger.warning(
                    f"[RISK] Daily loss limit hit: {daily_pct:.1f}% "
                    f"(limit: {max_loss}%)"
                )
                return {
                    "ok": False,
                    "daily_pct": round(daily_pct, 2),
                    "reason": f"Daily loss {daily_pct:.1f}% exceeds limit {max_loss}%"
                }
            return {"ok": True, "daily_pct": round(daily_pct, 2), "reason": "OK"}
        except Exception as e:
            return {"ok": True, "daily_pct": 0, "reason": "check error"}

    def reset_daily(self):
        """Call at start of each trading day"""
        try:
            self.day_start_value = self.client.get_portfolio_value()
            logger.info(f"[RISK] Day reset | Start value: ${self.day_start_value:,.2f}")
        except Exception:
            pass

    # ── 4. TRADE COOLDOWN ────────────────────────────────────
    def check_cooldown(self, symbol: str) -> bool:
        """Returns True if OK to trade, False if in cooldown"""
        cooldown_hours = getattr(config, "TRADE_COOLDOWN_HOURS", 1.0)
        last = self.last_trade_time.get(symbol)
        if last is None:
            return True
        hours_passed = (datetime.now() - last).total_seconds() / 3600
        if hours_passed < cooldown_hours:
            remaining = cooldown_hours - hours_passed
            logger.debug(f"[RISK] {symbol} in cooldown ({remaining:.1f}h remaining)")
            return False
        return True

    def record_trade(self, symbol: str):
        self.last_trade_time[symbol] = datetime.now()

    def clear_trailing(self, symbol: str):
        self.trailing_stops.pop(symbol, None)

    # ── 5. MULTI-TIMEFRAME TREND FILTER ──────────────────────
    def check_trend_alignment(self, symbol: str, signal: str,
                               alpaca_client) -> dict:
        """
        Before entering a BUY, check daily trend is also bullish.
        Before entering a SELL, check daily trend is bearish.
        Returns: { "aligned": bool, "reason": str }
        """
        try:
            df_daily = alpaca_client.get_bars(symbol, timeframe="1Day", limit=60)
            if df_daily.empty or len(df_daily) < 30:
                return {"aligned": True, "reason": "no daily data — allowing trade"}

            close    = df_daily["close"]
            ema20    = close.ewm(span=20, adjust=False).mean().iloc[-1]
            ema50    = close.ewm(span=50, adjust=False).mean().iloc[-1]
            price    = close.iloc[-1]

            daily_bullish = price > ema20 > ema50
            daily_bearish = price < ema20 < ema50

            if signal == "BUY":
                if daily_bearish:
                    return {
                        "aligned": False,
                        "reason": f"daily trend BEARISH (price ${price:.2f} < EMA20 ${ema20:.2f}) — skipping BUY"
                    }
                return {
                    "aligned": True,
                    "reason": f"daily {'bullish' if daily_bullish else 'neutral'} — OK for BUY"
                }
            elif signal == "SELL":
                if daily_bullish:
                    return {
                        "aligned": False,
                        "reason": f"daily trend BULLISH — skipping short SELL"
                    }
                return {"aligned": True, "reason": "daily supports SELL"}

        except Exception as e:
            logger.debug(f"[RISK] MTF check error for {symbol}: {e}")

        return {"aligned": True, "reason": "MTF check skipped"}

    # ── Summary for Telegram/Dashboard ───────────────────────
    def get_status(self) -> dict:
        dd   = self.check_drawdown()
        dl   = self.check_daily_loss()
        return {
            "halted":       self.halted,
            "drawdown_pct": dd["drawdown_pct"],
            "daily_pnl_pct": dl["daily_pct"],
            "peak_value":   self.peak_value,
            "trailing_active": list(self.trailing_stops.keys()),
        }
