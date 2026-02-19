"""
ALPHARAGHU - Strategy 1: Momentum (RSI + MACD + EMA)
=====================================================
LOGIC:
  BUY  when: Price > EMA200, RSI crosses above 50 from below,
             MACD line crosses above signal line,
             Volume > 1.5x average volume

  SELL when: RSI crosses below 50 from above,
             OR MACD line crosses below signal line,
             OR Stop loss / Take profit hit

WHY THIS WORKS:
  - EMA200 filters trades in the direction of the trend
  - RSI + MACD combo reduces false signals
  - Volume confirmation ensures real momentum
"""

import logging
import pandas as pd
import numpy as np

logger = logging.getLogger("alpharaghu.strategy.momentum")


class MomentumStrategy:
    name = "momentum"
    display_name = "📈 Momentum (RSI+MACD)"

    def __init__(self,
                 rsi_period: int = 14,
                 macd_fast: int = 12,
                 macd_slow: int = 26,
                 macd_signal: int = 9,
                 ema_period: int = 200,
                 volume_multiplier: float = 1.5):
        self.rsi_period       = rsi_period
        self.macd_fast        = macd_fast
        self.macd_slow        = macd_slow
        self.macd_signal      = macd_signal
        self.ema_period       = ema_period
        self.volume_multiplier = volume_multiplier

    # ── Indicator Calculations ───────────────────────────────
    def _calc_rsi(self, prices: pd.Series) -> pd.Series:
        delta  = prices.diff()
        gain   = delta.clip(lower=0)
        loss   = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=self.rsi_period - 1, min_periods=self.rsi_period).mean()
        avg_loss = loss.ewm(com=self.rsi_period - 1, min_periods=self.rsi_period).mean()
        rs  = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calc_macd(self, prices: pd.Series):
        ema_fast   = prices.ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow   = prices.ewm(span=self.macd_slow, adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal     = macd_line.ewm(span=self.macd_signal, adjust=False).mean()
        histogram  = macd_line - signal
        return macd_line, signal, histogram

    def _calc_ema(self, prices: pd.Series, period: int) -> pd.Series:
        return prices.ewm(span=period, adjust=False).mean()

    # ── Signal Generation ────────────────────────────────────
    def generate_signal(self, df: pd.DataFrame) -> dict:
        """
        Returns dict: {
          signal: 'BUY' | 'SELL' | 'HOLD',
          strength: 0.0 - 1.0,
          reason: str,
          indicators: dict
        }
        """
        if len(df) < 60:  # Need at least 60 bars minimum
            return self._no_signal("Not enough data")

        close  = df["close"]
        volume = df["volume"]

        # Calculate indicators
        rsi        = self._calc_rsi(close)
        macd, sig, hist = self._calc_macd(close)
        ema200     = self._calc_ema(close, self.ema_period)
        ema50      = self._calc_ema(close, 50)
        avg_vol    = volume.rolling(20).mean()

        # Latest values
        latest_close  = close.iloc[-1]
        latest_rsi    = rsi.iloc[-1]
        prev_rsi      = rsi.iloc[-2]
        latest_macd   = macd.iloc[-1]
        prev_macd     = macd.iloc[-2]
        latest_sig    = sig.iloc[-1]
        prev_sig      = sig.iloc[-2]
        latest_ema200 = ema200.iloc[-1]
        latest_ema50  = ema50.iloc[-1]
        latest_vol    = volume.iloc[-1]
        avg_vol_val   = avg_vol.iloc[-1]

        indicators = {
            "rsi":     round(latest_rsi, 2),
            "macd":    round(latest_macd, 4),
            "signal":  round(latest_sig, 4),
            "ema200":  round(latest_ema200, 2),
            "ema50":   round(latest_ema50, 2),
            "price":   round(latest_close, 2),
            "vol_ratio": round(latest_vol / avg_vol_val, 2) if avg_vol_val else 0,
        }

        # ── BUY Conditions ────────────────────────────────────
        above_ema200     = latest_close > latest_ema200
        above_ema50      = latest_close > latest_ema50
        rsi_cross_up     = prev_rsi < 52 and latest_rsi >= 48  # Wider band
        macd_cross_up    = prev_macd < prev_sig and latest_macd >= latest_sig
        volume_confirmed = latest_vol > avg_vol_val * self.volume_multiplier
        rsi_not_overbought = latest_rsi < 75

        buy_score = sum([
            above_ema200     * 1.0,  # Reduced — EMA200 too strict on 15min
            above_ema50      * 0.5,
            rsi_cross_up     * 2.0,
            macd_cross_up    * 2.0,
            volume_confirmed * 1.0,
            rsi_not_overbought * 1.0,
        ])
        buy_max = 8.0

        # ── SELL Conditions ───────────────────────────────────
        below_ema200   = latest_close < latest_ema200
        rsi_cross_down = prev_rsi > 48 and latest_rsi <= 52  # Wider band
        macd_cross_down = prev_macd > prev_sig and latest_macd <= latest_sig
        rsi_overbought = latest_rsi > 75

        sell_score = sum([
            below_ema200    * 2.0,
            rsi_cross_down  * 2.0,
            macd_cross_down * 2.0,
            rsi_overbought  * 1.0,
        ])
        sell_max = 7.0

        # ── Decision ──────────────────────────────────────────
        buy_strength  = buy_score  / buy_max
        sell_strength = sell_score / sell_max

        if buy_strength >= 0.45 and buy_strength > sell_strength:
            reasons = []
            if above_ema200:     reasons.append("price above EMA200")
            if rsi_cross_up:     reasons.append(f"RSI crossed 50 ({latest_rsi:.1f})")
            if macd_cross_up:    reasons.append("MACD bullish crossover")
            if volume_confirmed: reasons.append(f"volume {indicators['vol_ratio']}x avg")
            return {
                "signal": "BUY",
                "strength": round(buy_strength, 2),
                "reason": " | ".join(reasons),
                "indicators": indicators
            }

        elif sell_strength >= 0.45 and sell_strength > buy_strength:
            reasons = []
            if below_ema200:    reasons.append("price below EMA200")
            if rsi_cross_down:  reasons.append(f"RSI dropped below 50 ({latest_rsi:.1f})")
            if macd_cross_down: reasons.append("MACD bearish crossover")
            if rsi_overbought:  reasons.append(f"RSI overbought ({latest_rsi:.1f})")
            return {
                "signal": "SELL",
                "strength": round(sell_strength, 2),
                "reason": " | ".join(reasons),
                "indicators": indicators
            }

        return self._no_signal(
            f"No clear signal | RSI:{latest_rsi:.1f} | "
            f"Buy:{buy_strength:.0%} Sell:{sell_strength:.0%}"
        )

    def _no_signal(self, reason: str) -> dict:
        return {"signal": "HOLD", "strength": 0.0, "reason": reason, "indicators": {}}
