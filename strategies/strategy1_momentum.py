"""
ALPHARAGHU - Strategy 1: Momentum (RSI + MACD + EMA + HH/LL Structure)
========================================================================
LOGIC:
  BUY  when: Price > EMA200, RSI crosses above 50,
             MACD bullish crossover, Volume confirmed,
             AND market making Higher Highs (uptrend structure)

  SELL when: RSI crosses below 50, MACD bearish crossover,
             OR market making Lower Lows (downtrend structure)

WHY HH/LL MATTERS:
  - EMAs tell you WHERE price is relative to average
  - HH/LL tells you WHERE price is GOING (actual trend direction)
  - Combining both = fewer false signals in choppy/ranging markets
  - Example: EMAs can be bullish but price making LL = trap, skip it

MARKET STRUCTURE:
  Higher High (HH): recent high > previous high  → uptrend
  Lower Low  (LL):  recent low  < previous low   → downtrend
  Ranging:          neither HH nor LL             → no clear direction
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
    def generate_signal(self, df: pd.DataFrame, vwap: float = 0.0) -> dict:
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

        # ── HH/LL Market Structure Detection ─────────────────
        # Use last 20 bars, split into 3 windows to find swing points
        # Window: recent(last 5) vs mid(5-10 ago) vs prior(10-20 ago)
        n = min(len(df), 20)
        highs = df["high"].iloc[-n:]
        lows  = df["low"].iloc[-n:]

        recent_high = highs.iloc[-5:].max()   # Last 5 bars
        prior_high  = highs.iloc[-15:-5].max() if n >= 15 else highs.iloc[:-5].max()
        recent_low  = lows.iloc[-5:].min()
        prior_low   = lows.iloc[-15:-5].min()  if n >= 15 else lows.iloc[:-5].min()

        is_higher_high = recent_high > prior_high   # Uptrend: making new highs
        is_lower_low   = recent_low  < prior_low    # Downtrend: making new lows
        is_higher_low  = recent_low  > prior_low    # Healthy uptrend: lows rising
        is_lower_high  = recent_high < prior_high   # Healthy downtrend: highs falling

        # Structure classification
        if is_higher_high and is_higher_low:
            structure = "HH_HL"      # Strong uptrend — best for BUY
        elif is_higher_high:
            structure = "HH"         # Uptrend (lows not confirmed yet)
        elif is_lower_low and is_lower_high:
            structure = "LL_LH"      # Strong downtrend — best for SELL
        elif is_lower_low:
            structure = "LL"         # Downtrend (highs not confirmed yet)
        else:
            structure = "RANGING"    # Choppy — avoid new entries

        # ── VWAP Confirmation ─────────────────────────────────
        # VWAP = intraday 'fair price' — institutions buy above, sell below
        # If vwap was passed in, use it; otherwise treat as neutral
        above_vwap = (vwap > 0 and latest_close > vwap)
        vwap_str   = f"${vwap:.2f}" if vwap > 0 else "N/A"

        indicators = {
            "rsi":       round(latest_rsi, 2),
            "macd":      round(latest_macd, 4),
            "signal":    round(latest_sig, 4),
            "ema200":    round(latest_ema200, 2),
            "ema50":     round(latest_ema50, 2),
            "price":     round(latest_close, 2),
            "vwap":      round(vwap, 2) if vwap > 0 else None,
            "above_vwap": above_vwap,
            "vol_ratio": round(latest_vol / avg_vol_val, 2) if avg_vol_val else 0,
            "structure": structure,
            "hh": is_higher_high, "hl": is_higher_low,
            "ll": is_lower_low,   "lh": is_lower_high,
        }

        # ── BUY Conditions ────────────────────────────────────
        above_ema200       = latest_close > latest_ema200
        above_ema50        = latest_close > latest_ema50
        rsi_cross_up       = prev_rsi < 52 and latest_rsi >= 48
        macd_cross_up      = prev_macd < prev_sig and latest_macd >= latest_sig
        volume_confirmed   = latest_vol > avg_vol_val * self.volume_multiplier
        rsi_not_overbought = latest_rsi < 75

        # HH/LL structure bonuses
        structure_bullish  = is_higher_high                 # Making new highs
        structure_strong   = is_higher_high and is_higher_low  # Both HH and HL = strong
        structure_ranging  = not is_higher_high and not is_lower_low  # Avoid chop

        buy_score = sum([
            above_ema200       * 1.0,
            above_ema50        * 0.5,
            rsi_cross_up       * 2.0,
            macd_cross_up      * 2.0,
            volume_confirmed   * 1.0,
            rsi_not_overbought * 0.5,
            structure_bullish  * 1.5,   # HH = uptrend confirmed
            structure_strong   * 0.5,   # HH+HL = strongest signal bonus
            not structure_ranging * 0.0, # Ranging = no bonus (not penalized)
            above_vwap         * 0.5,   # Above VWAP = institutional support
        ])
        buy_max = 10.0  # Updated max with VWAP score

        # ── SELL Conditions ───────────────────────────────────
        below_ema200    = latest_close < latest_ema200
        rsi_cross_down  = prev_rsi > 48 and latest_rsi <= 52
        macd_cross_down = prev_macd > prev_sig and latest_macd <= latest_sig
        rsi_overbought  = latest_rsi > 75

        # HH/LL structure for sell
        structure_bearish = is_lower_low                    # Making new lows
        structure_strong_bear = is_lower_low and is_lower_high  # Both LL and LH

        sell_score = sum([
            below_ema200        * 2.0,
            rsi_cross_down      * 2.0,
            macd_cross_down     * 2.0,
            rsi_overbought      * 1.0,
            structure_bearish   * 1.5,  # LL = downtrend confirmed
            structure_strong_bear * 0.5, # LL+LH = strongest sell bonus
        ])
        sell_max = 9.5   # Updated max with structure scores

        # ── Decision ──────────────────────────────────────────
        buy_strength  = buy_score  / buy_max
        sell_strength = sell_score / sell_max

        if buy_strength >= 0.45 and buy_strength > sell_strength:
            reasons = []
            if above_ema200:       reasons.append("price above EMA200")
            if rsi_cross_up:       reasons.append(f"RSI crossed 50 ({latest_rsi:.1f})")
            if macd_cross_up:      reasons.append("MACD bullish crossover")
            if volume_confirmed:   reasons.append(f"vol {indicators['vol_ratio']}x avg")
            if above_vwap:         reasons.append(f"above VWAP ({vwap_str})")
            if structure_strong:   reasons.append(f"structure: HH+HL (strong uptrend)")
            elif structure_bullish: reasons.append(f"structure: HH (new highs)")
            elif structure_ranging: reasons.append("structure: ranging (weak)")
            return {
                "signal": "BUY",
                "strength": round(buy_strength, 2),
                "reason": " | ".join(reasons),
                "indicators": indicators
            }

        elif sell_strength >= 0.45 and sell_strength > buy_strength:
            reasons = []
            if below_ema200:          reasons.append("price below EMA200")
            if rsi_cross_down:        reasons.append(f"RSI dropped below 50 ({latest_rsi:.1f})")
            if macd_cross_down:       reasons.append("MACD bearish crossover")
            if rsi_overbought:        reasons.append(f"RSI overbought ({latest_rsi:.1f})")
            if structure_strong_bear: reasons.append("structure: LL+LH (strong downtrend)")
            elif structure_bearish:   reasons.append("structure: LL (new lows)")
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
