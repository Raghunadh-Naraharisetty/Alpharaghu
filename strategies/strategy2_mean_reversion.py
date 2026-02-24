"""
ALPHARAGHU - Strategy 2: Mean Reversion (BB + RSI + Stochastic + StochRSI + CMF)
==================================================================================
LOGIC:
  BUY  when: Price touches/crosses below Lower Bollinger Band,
             RSI < 35 (oversold), Stochastic %K < 20 + crosses up,
             Volume spike confirms reversal
             + pandas-ta: StochRSI < 20 (extra sensitive oversold)
                          CMF > 0 (money flowing in despite price dip)

  SELL when: Price reaches Middle/Upper Band, RSI > 65, Stochastic overbought
             + pandas-ta: StochRSI > 80 + CMF < 0

NEW (pandas-ta):
  StochRSI — RSI applied to RSI. Far more sensitive than regular RSI.
             StochRSI_K < 20 = extremely oversold — very high bounce probability.
             StochRSI_K > 80 = extremely overbought.
             Gives earlier warnings than RSI alone.

  CMF (Chaikin Money Flow) — measures buying/selling pressure by volume.
             CMF > 0  = money flowing IN  (institutions accumulating despite dip → bounce)
             CMF < 0  = money flowing OUT (distribution → avoid buying the dip)
             CMF > 0.1 = strong accumulation signal.
             This catches the difference between an oversold bounce vs a stock in freefall.
"""

import logging
import pandas as pd
import numpy as np

logger = logging.getLogger("alpharaghu.strategy.mean_reversion")

try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
    logger.debug("[mean_rev] pandas-ta loaded — StochRSI + CMF active")
except ImportError:
    HAS_PANDAS_TA = False
    logger.warning("[mean_rev] pandas-ta not installed. Install with: pip install pandas-ta")


class MeanReversionStrategy:
    name = "mean_reversion"
    display_name = "🔄 Mean Reversion (BB+StochRSI+CMF)"

    def __init__(self,
                 bb_period: int = 20,
                 bb_std: float = 2.0,
                 rsi_period: int = 14,
                 rsi_oversold: float = 35,
                 rsi_overbought: float = 65,
                 stoch_k: int = 14,
                 stoch_d: int = 3,
                 cmf_period: int = 20):
        self.bb_period      = bb_period
        self.bb_std         = bb_std
        self.rsi_period     = rsi_period
        self.rsi_oversold   = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.stoch_k        = stoch_k
        self.stoch_d        = stoch_d
        self.cmf_period     = cmf_period

    # ── Core indicators (hand-coded, no deps) ─────────────────
    def _calc_bollinger(self, prices: pd.Series):
        sma   = prices.rolling(self.bb_period).mean()
        std   = prices.rolling(self.bb_period).std()
        upper = sma + (std * self.bb_std)
        lower = sma - (std * self.bb_std)
        width = (upper - lower) / sma   # Bandwidth
        return upper, sma, lower, width

    def _calc_rsi(self, prices: pd.Series) -> pd.Series:
        delta    = prices.diff()
        gain     = delta.clip(lower=0)
        loss     = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=self.rsi_period - 1, min_periods=self.rsi_period).mean()
        avg_loss = loss.ewm(com=self.rsi_period - 1, min_periods=self.rsi_period).mean()
        rs       = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def _calc_stochastic(self, df: pd.DataFrame):
        low_min  = df["low"].rolling(self.stoch_k).min()
        high_max = df["high"].rolling(self.stoch_k).max()
        pct_k    = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
        pct_d    = pct_k.rolling(self.stoch_d).mean()
        return pct_k, pct_d

    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high, low, close = df["high"], df["low"], df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    # ── pandas-ta powered indicators (optional) ───────────────
    def _calc_stochrsi_cmf(self, df: pd.DataFrame):
        """
        Returns (stochrsi_k, stochrsi_oversold, stochrsi_overbought,
                 stochrsi_cross_up, cmf_val, cmf_accumulating).
        Falls back to neutral defaults if pandas-ta unavailable.
        """
        stochrsi_k          = 50.0
        stochrsi_oversold   = False
        stochrsi_overbought = False
        stochrsi_cross_up   = False
        stochrsi_cross_down = False
        cmf_val             = 0.0
        cmf_accumulating    = False   # CMF > 0 = money flowing in

        if not HAS_PANDAS_TA or len(df) < 30:
            return (stochrsi_k, stochrsi_oversold, stochrsi_overbought,
                    stochrsi_cross_up, stochrsi_cross_down, cmf_val, cmf_accumulating)

        # ── StochRSI ─────────────────────────────────────────
        try:
            srsi = ta.stochrsi(df["close"], length=14, rsi_length=14, k=3, d=3)
            if srsi is not None:
                k_cols = [c for c in srsi.columns if "STOCHRSIk" in c]
                d_cols = [c for c in srsi.columns if "STOCHRSId" in c]
                if k_cols and d_cols:
                    sk_now  = float(srsi[k_cols[0]].iloc[-1])
                    sk_prev = float(srsi[k_cols[0]].iloc[-2])
                    sd_now  = float(srsi[d_cols[0]].iloc[-1])
                    sd_prev = float(srsi[d_cols[0]].iloc[-2])
                    if not pd.isna(sk_now):
                        stochrsi_k          = sk_now
                        stochrsi_oversold   = sk_now < 20
                        stochrsi_overbought = sk_now > 80
                        stochrsi_cross_up   = (sk_prev < sd_prev and sk_now >= sd_now
                                               and sk_now < 50)
                        stochrsi_cross_down = (sk_prev > sd_prev and sk_now <= sd_now
                                               and sk_now > 50)
        except Exception as e:
            logger.debug(f"[mean_rev] StochRSI calc error: {e}")

        # ── CMF (Chaikin Money Flow) ──────────────────────────
        try:
            cmf_series = ta.cmf(df["high"], df["low"], df["close"],
                                df["volume"], length=self.cmf_period)
            if cmf_series is not None:
                v = cmf_series.iloc[-1]
                if not pd.isna(v):
                    cmf_val          = float(v)
                    cmf_accumulating = cmf_val > 0.0   # Money flowing in
        except Exception as e:
            logger.debug(f"[mean_rev] CMF calc error: {e}")

        return (stochrsi_k, stochrsi_oversold, stochrsi_overbought,
                stochrsi_cross_up, stochrsi_cross_down, cmf_val, cmf_accumulating)

    # ── Signal Generation ─────────────────────────────────────
    def generate_signal(self, df: pd.DataFrame) -> dict:
        if len(df) < 40:
            return self._no_signal("Not enough data")

        close  = df["close"]
        volume = df["volume"]

        upper_bb, mid_bb, lower_bb, bb_width = self._calc_bollinger(close)
        rsi              = self._calc_rsi(close)
        stoch_k, stoch_d = self._calc_stochastic(df)
        atr              = self._calc_atr(df)
        avg_vol          = volume.rolling(20).mean()

        price    = close.iloc[-1]
        rsi_now  = rsi.iloc[-1];    rsi_prev  = rsi.iloc[-2]
        k_now    = stoch_k.iloc[-1]; k_prev   = stoch_k.iloc[-2]
        d_now    = stoch_d.iloc[-1]; d_prev   = stoch_d.iloc[-2]
        upper    = upper_bb.iloc[-1]; mid     = mid_bb.iloc[-1]
        lower    = lower_bb.iloc[-1]; width   = bb_width.iloc[-1]
        atr_val  = atr.iloc[-1]
        vol_ratio= volume.iloc[-1] / avg_vol.iloc[-1] if avg_vol.iloc[-1] else 1

        if bb_width.iloc[-1] < 0.02:
            return self._no_signal("BB squeeze — skipping mean reversion")

        # ── StochRSI + CMF (pandas-ta) ────────────────────────
        (stochrsi_k, stochrsi_oversold, stochrsi_overbought,
         stochrsi_cross_up, stochrsi_cross_down,
         cmf_val, cmf_accumulating) = self._calc_stochrsi_cmf(df)

        # ── HH/LL Market Structure ────────────────────────────
        n           = min(len(df), 20)
        highs       = df["high"].iloc[-n:]
        lows        = df["low"].iloc[-n:]
        recent_high = highs.iloc[-5:].max()
        prior_high  = highs.iloc[-15:-5].max() if n >= 15 else highs.iloc[:-5].max()
        recent_low  = lows.iloc[-5:].min()
        prior_low   = lows.iloc[-15:-5].min()  if n >= 15 else lows.iloc[:-5].min()

        is_higher_high   = recent_high > prior_high
        is_lower_low     = recent_low  < prior_low
        is_higher_low    = recent_low  > prior_low
        is_lower_high    = recent_high < prior_high
        strong_downtrend = is_lower_low and is_lower_high
        uptrend_dip      = is_higher_high or is_higher_low

        indicators = {
            "price":         round(price, 2),
            "rsi":           round(rsi_now, 2),
            "stoch_k":       round(k_now, 2),
            "stoch_d":       round(d_now, 2),
            "bb_upper":      round(upper, 2),
            "bb_mid":        round(mid, 2),
            "bb_lower":      round(lower, 2),
            "bb_width":      round(width * 100, 2),
            "atr":           round(atr_val, 3),
            "vol_ratio":     round(vol_ratio, 2),
            "stochrsi_k":    round(stochrsi_k, 1),
            "cmf":           round(cmf_val, 3),
            "cmf_signal":    "accumulating" if cmf_accumulating else "distributing",
            "structure":     (
                "HH+HL (uptrend)" if is_higher_high and is_higher_low else
                "LL+LH (downtrend)" if strong_downtrend else
                "HH" if is_higher_high else
                "LL" if is_lower_low else "ranging"
            ),
        }

        # ── BUY (Oversold Bounce) ─────────────────────────────
        price_at_lower   = price <= lower * 1.015
        rsi_oversold     = rsi_now < self.rsi_oversold
        stoch_oversold   = k_now < 25
        stoch_k_cross_up = k_prev < d_prev and k_now >= d_now
        rsi_turning_up   = rsi_now > rsi_prev

        buy_score = sum([
            price_at_lower      * 3.0,
            rsi_oversold        * 2.0,
            stoch_oversold      * 1.5,
            stoch_k_cross_up    * 2.0,
            rsi_turning_up      * 1.0,
            (vol_ratio > 1.3)   * 0.5,
            uptrend_dip         * 1.0,
            (not strong_downtrend) * 0.5,
            # pandas-ta additions ─────────────────────────────
            stochrsi_oversold   * 2.0,   # StochRSI < 20 = extreme oversold
            stochrsi_cross_up   * 1.5,   # StochRSI turning up = momentum shift
            cmf_accumulating    * 1.5,   # Money flowing in despite price dip
            (cmf_val > 0.1)     * 0.5,   # Strong accumulation bonus
        ])
        buy_max = 17.5

        # ── SELL (Overbought / Mean Target) ───────────────────
        price_at_upper     = price >= upper * 0.985
        price_at_mid       = price >= mid * 0.995
        rsi_overbought     = rsi_now > self.rsi_overbought
        stoch_overbought   = k_now > 75
        stoch_k_cross_down = k_prev > d_prev and k_now <= d_now
        strong_uptrend     = is_higher_high and is_higher_low

        sell_score = sum([
            price_at_upper       * 3.0,
            price_at_mid         * 1.5,
            rsi_overbought       * 2.0,
            stoch_overbought     * 1.5,
            stoch_k_cross_down   * 2.0,
            (not strong_uptrend) * 0.5,
            # pandas-ta additions ─────────────────────────────
            stochrsi_overbought  * 2.0,   # StochRSI > 80 = extreme overbought
            stochrsi_cross_down  * 1.5,   # StochRSI turning down
            (not cmf_accumulating) * 1.0, # Money flowing out = distribution
        ])
        sell_max = 15.0

        buy_strength  = buy_score  / buy_max
        sell_strength = sell_score / sell_max

        if buy_strength >= 0.38 and buy_strength > sell_strength:
            reasons = []
            if price_at_lower:      reasons.append(f"price at Lower BB ({lower:.2f})")
            if rsi_oversold:        reasons.append(f"RSI oversold ({rsi_now:.1f})")
            if stoch_k_cross_up:    reasons.append(f"Stoch %K crossover ({k_now:.1f})")
            if rsi_turning_up:      reasons.append("RSI turning up")
            if HAS_PANDAS_TA:
                if stochrsi_oversold:  reasons.append(f"StochRSI oversold ({stochrsi_k:.0f})")
                if cmf_accumulating:   reasons.append(f"CMF accumulating ({cmf_val:+.2f})")
            return {
                "signal": "BUY", "strength": round(buy_strength, 2),
                "reason": " | ".join(reasons), "indicators": indicators,
                "targets": {
                    "entry":  round(price, 2),
                    "target": round(mid, 2),
                    "stop":   round(price - 2 * atr_val, 2),
                },
            }

        elif sell_strength >= 0.38 and sell_strength > buy_strength:
            reasons = []
            if price_at_upper:       reasons.append(f"price at Upper BB ({upper:.2f})")
            if price_at_mid:         reasons.append(f"reached mean ({mid:.2f})")
            if rsi_overbought:       reasons.append(f"RSI overbought ({rsi_now:.1f})")
            if stoch_k_cross_down:   reasons.append(f"Stoch %K bearish ({k_now:.1f})")
            if HAS_PANDAS_TA:
                if stochrsi_overbought: reasons.append(f"StochRSI overbought ({stochrsi_k:.0f})")
                if not cmf_accumulating: reasons.append(f"CMF distributing ({cmf_val:+.2f})")
            return {
                "signal": "SELL", "strength": round(sell_strength, 2),
                "reason": " | ".join(reasons), "indicators": indicators,
            }

        return self._no_signal(
            f"In band | RSI:{rsi_now:.1f} | StochRSI:{stochrsi_k:.0f} | "
            f"CMF:{cmf_val:+.2f} | Buy:{buy_strength:.0%} Sell:{sell_strength:.0%}"
        )

    def _no_signal(self, reason: str) -> dict:
        return {"signal": "HOLD", "strength": 0.0, "reason": reason, "indicators": {}}
