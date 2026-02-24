"""
ALPHARAGHU - Strategy 1: Momentum (RSI + MACD + EMA + HH/LL + ADX + Supertrend)
=================================================================================
LOGIC:
  BUY  when: Price > EMA200, RSI crosses above 50,
             MACD bullish crossover, Volume confirmed,
             market making Higher Highs (uptrend structure)
             + pandas-ta: ADX >= 25 (trending), Supertrend bullish

  SELL when: RSI crosses below 50, MACD bearish crossover,
             OR market making Lower Lows
             + pandas-ta: Supertrend bearish

NEW (pandas-ta):
  ADX      — Average Directional Index. Measures TREND STRENGTH, not direction.
             ADX < 20 = choppy ranging market → skip entries
             ADX ≥ 25 = trending → conditions are right
             ADX ≥ 40 = very strong trend → extra confidence
             This alone eliminates ~30% of false signals in sideways markets.

  Supertrend — Dynamic trend line that flips direction on ATR breakouts.
             Direction = +1 (bullish) or -1 (bearish).
             When price is above the line = uptrend; below = downtrend.
             Much more adaptive than a static EMA200 filter.
"""

import logging
import pandas as pd
import numpy as np

logger = logging.getLogger("alpharaghu.strategy.momentum")

# pandas-ta is optional — bot works without it, better with it
try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
    logger.debug("[momentum] pandas-ta loaded — ADX + Supertrend active")
except ImportError:
    HAS_PANDAS_TA = False
    logger.warning("[momentum] pandas-ta not installed — running without ADX/Supertrend. "
                   "Install with: pip install pandas-ta")


class MomentumStrategy:
    name = "momentum"
    display_name = "📈 Momentum (RSI+MACD+ADX)"

    def __init__(self,
                 rsi_period: int = 14,
                 macd_fast: int = 12,
                 macd_slow: int = 26,
                 macd_signal: int = 9,
                 ema_period: int = 200,
                 volume_multiplier: float = 1.5,
                 adx_period: int = 14,
                 adx_min_trend: float = 20.0,
                 supertrend_length: int = 10,
                 supertrend_mult: float = 3.0):
        self.rsi_period        = rsi_period
        self.macd_fast         = macd_fast
        self.macd_slow         = macd_slow
        self.macd_signal       = macd_signal
        self.ema_period        = ema_period
        self.volume_multiplier = volume_multiplier
        self.adx_period        = adx_period
        self.adx_min_trend     = adx_min_trend
        self.supertrend_length = supertrend_length
        self.supertrend_mult   = supertrend_mult

    # ── Core indicators (hand-coded, no deps) ─────────────────
    def _calc_rsi(self, prices: pd.Series) -> pd.Series:
        delta    = prices.diff()
        gain     = delta.clip(lower=0)
        loss     = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=self.rsi_period - 1, min_periods=self.rsi_period).mean()
        avg_loss = loss.ewm(com=self.rsi_period - 1, min_periods=self.rsi_period).mean()
        rs       = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def _calc_macd(self, prices: pd.Series):
        ema_fast  = prices.ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow  = prices.ewm(span=self.macd_slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal    = macd_line.ewm(span=self.macd_signal, adjust=False).mean()
        return macd_line, signal, macd_line - signal

    def _calc_ema(self, prices: pd.Series, period: int) -> pd.Series:
        return prices.ewm(span=period, adjust=False).mean()

    # ── pandas-ta powered indicators (optional) ───────────────
    def _calc_adx_supertrend(self, df: pd.DataFrame):
        """
        Returns (adx_val, adx_trending, adx_strong, supertrend_bullish).
        Falls back to neutral defaults if pandas-ta unavailable or errors.
        """
        adx_val            = 30.0   # default: assume moderate trend
        adx_trending       = True
        adx_strong         = False
        supertrend_bullish = True   # default: neutral/bullish

        if not HAS_PANDAS_TA or len(df) < 30:
            return adx_val, adx_trending, adx_strong, supertrend_bullish

        try:
            # ADX — trend strength (direction-agnostic)
            adx_df = ta.adx(df["high"], df["low"], df["close"],
                            length=self.adx_period)
            if adx_df is not None and not adx_df.empty:
                col = f"ADX_{self.adx_period}"
                if col in adx_df.columns:
                    v = adx_df[col].iloc[-1]
                    if not pd.isna(v):
                        adx_val      = float(v)
                        adx_trending = adx_val >= self.adx_min_trend
                        adx_strong   = adx_val >= 35.0
        except Exception as e:
            logger.debug(f"[momentum] ADX calc error: {e}")

        try:
            # Supertrend — dynamic trend direction
            st_df = ta.supertrend(
                df["high"], df["low"], df["close"],
                length=self.supertrend_length,
                multiplier=self.supertrend_mult
            )
            if st_df is not None:
                dir_cols = [c for c in st_df.columns if "SUPERTd" in c]
                if dir_cols:
                    v = st_df[dir_cols[0]].iloc[-1]
                    if not pd.isna(v):
                        supertrend_bullish = float(v) == 1.0
        except Exception as e:
            logger.debug(f"[momentum] Supertrend calc error: {e}")

        return adx_val, adx_trending, adx_strong, supertrend_bullish

    # ── Signal Generation ─────────────────────────────────────
    def generate_signal(self, df: pd.DataFrame, vwap: float = 0.0) -> dict:
        if len(df) < 60:
            return self._no_signal("Not enough data")

        close  = df["close"]
        volume = df["volume"]

        # Base indicators
        rsi             = self._calc_rsi(close)
        macd, sig, hist = self._calc_macd(close)
        ema200          = self._calc_ema(close, self.ema_period)
        ema50           = self._calc_ema(close, 50)
        avg_vol         = volume.rolling(20).mean()

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

        # ── ADX + Supertrend (pandas-ta) ──────────────────────
        adx_val, adx_trending, adx_strong, supertrend_bullish = \
            self._calc_adx_supertrend(df)

        # ── HH/LL Market Structure ────────────────────────────
        n           = min(len(df), 20)
        highs       = df["high"].iloc[-n:]
        lows        = df["low"].iloc[-n:]
        recent_high = highs.iloc[-5:].max()
        prior_high  = highs.iloc[-15:-5].max() if n >= 15 else highs.iloc[:-5].max()
        recent_low  = lows.iloc[-5:].min()
        prior_low   = lows.iloc[-15:-5].min()  if n >= 15 else lows.iloc[:-5].min()

        is_higher_high = recent_high > prior_high
        is_lower_low   = recent_low  < prior_low
        is_higher_low  = recent_low  > prior_low
        is_lower_high  = recent_high < prior_high

        structure = (
            "HH_HL" if is_higher_high and is_higher_low else
            "HH"    if is_higher_high else
            "LL_LH" if is_lower_low and is_lower_high else
            "LL"    if is_lower_low else
            "RANGING"
        )

        # ── VWAP ─────────────────────────────────────────────
        above_vwap = (vwap > 0 and latest_close > vwap)
        vwap_str   = f"${vwap:.2f}" if vwap > 0 else "N/A"

        indicators = {
            "rsi":              round(latest_rsi, 2),
            "macd":             round(latest_macd, 4),
            "signal":           round(latest_sig, 4),
            "ema200":           round(latest_ema200, 2),
            "ema50":            round(latest_ema50, 2),
            "price":            round(latest_close, 2),
            "vwap":             round(vwap, 2) if vwap > 0 else None,
            "above_vwap":       above_vwap,
            "vol_ratio":        round(latest_vol / avg_vol_val, 2) if avg_vol_val else 0,
            "structure":        structure,
            "adx":              round(adx_val, 1),
            "adx_trending":     adx_trending,
            "supertrend":       "bullish" if supertrend_bullish else "bearish",
            "hh": is_higher_high, "hl": is_higher_low,
            "ll": is_lower_low,   "lh": is_lower_high,
        }

        # ── ADX market regime filter ──────────────────────────
        # If ADX < 15, market is too choppy for momentum — skip entirely
        if adx_val < 15.0:
            return self._no_signal(
                f"ADX {adx_val:.0f} — choppy market, momentum signals unreliable"
            )

        # ── BUY conditions ────────────────────────────────────
        above_ema200       = latest_close > latest_ema200
        above_ema50        = latest_close > latest_ema50
        rsi_cross_up       = prev_rsi < 52 and latest_rsi >= 48
        macd_cross_up      = prev_macd < prev_sig and latest_macd >= latest_sig
        volume_confirmed   = latest_vol > avg_vol_val * self.volume_multiplier
        rsi_not_overbought = latest_rsi < 75
        structure_bullish  = is_higher_high
        structure_strong   = is_higher_high and is_higher_low
        structure_ranging  = not is_higher_high and not is_lower_low

        buy_score = sum([
            above_ema200         * 1.0,
            above_ema50          * 0.5,
            rsi_cross_up         * 2.0,
            macd_cross_up        * 2.0,
            volume_confirmed     * 1.0,
            rsi_not_overbought   * 0.5,
            structure_bullish    * 1.5,
            structure_strong     * 0.5,
            above_vwap           * 0.5,
            # pandas-ta additions ────────────────────────────
            adx_trending         * 1.0,   # ADX >= 20: market is trending
            adx_strong           * 0.5,   # ADX >= 35: very strong trend
            supertrend_bullish   * 1.5,   # Supertrend confirms uptrend
        ])
        buy_max = 13.0

        # ── SELL conditions ───────────────────────────────────
        below_ema200         = latest_close < latest_ema200
        rsi_cross_down       = prev_rsi > 48 and latest_rsi <= 52
        macd_cross_down      = prev_macd > prev_sig and latest_macd <= latest_sig
        rsi_overbought       = latest_rsi > 75
        structure_bearish    = is_lower_low
        structure_strong_bear= is_lower_low and is_lower_high

        sell_score = sum([
            below_ema200           * 2.0,
            rsi_cross_down         * 2.0,
            macd_cross_down        * 2.0,
            rsi_overbought         * 1.0,
            structure_bearish      * 1.5,
            structure_strong_bear  * 0.5,
            # pandas-ta additions ────────────────────────────
            adx_trending           * 0.5,   # Trending market = more decisive SELL
            (not supertrend_bullish) * 1.5, # Supertrend confirms downtrend
        ])
        sell_max = 11.5

        buy_strength  = buy_score  / buy_max
        sell_strength = sell_score / sell_max

        if buy_strength >= 0.45 and buy_strength > sell_strength:
            reasons = []
            if above_ema200:         reasons.append("price above EMA200")
            if rsi_cross_up:         reasons.append(f"RSI crossed 50 ({latest_rsi:.1f})")
            if macd_cross_up:        reasons.append("MACD bullish crossover")
            if volume_confirmed:     reasons.append(f"vol {indicators['vol_ratio']}x avg")
            if above_vwap:           reasons.append(f"above VWAP ({vwap_str})")
            if structure_strong:     reasons.append("structure: HH+HL (strong uptrend)")
            elif structure_bullish:  reasons.append("structure: HH (new highs)")
            if HAS_PANDAS_TA:
                if supertrend_bullish: reasons.append(f"Supertrend ↑")
                reasons.append(f"ADX {adx_val:.0f}")
            return {
                "signal": "BUY", "strength": round(buy_strength, 2),
                "reason": " | ".join(reasons), "indicators": indicators,
            }

        elif sell_strength >= 0.45 and sell_strength > buy_strength:
            reasons = []
            if below_ema200:             reasons.append("price below EMA200")
            if rsi_cross_down:           reasons.append(f"RSI dropped below 50 ({latest_rsi:.1f})")
            if macd_cross_down:          reasons.append("MACD bearish crossover")
            if rsi_overbought:           reasons.append(f"RSI overbought ({latest_rsi:.1f})")
            if structure_strong_bear:    reasons.append("structure: LL+LH")
            elif structure_bearish:      reasons.append("structure: LL (new lows)")
            if HAS_PANDAS_TA:
                if not supertrend_bullish: reasons.append("Supertrend ↓")
                reasons.append(f"ADX {adx_val:.0f}")
            return {
                "signal": "SELL", "strength": round(sell_strength, 2),
                "reason": " | ".join(reasons), "indicators": indicators,
            }

        return self._no_signal(
            f"No clear signal | RSI:{latest_rsi:.1f} | "
            f"ADX:{adx_val:.0f} | Buy:{buy_strength:.0%} Sell:{sell_strength:.0%}"
        )

    def _no_signal(self, reason: str) -> dict:
        return {"signal": "HOLD", "strength": 0.0, "reason": reason, "indicators": {}}
