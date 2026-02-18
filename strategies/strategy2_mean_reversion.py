"""
ALPHARAGHU - Strategy 2: Mean Reversion (Bollinger Bands + RSI + Stochastic)
=============================================================================
LOGIC:
  BUY  when: Price touches/crosses below Lower Bollinger Band,
             RSI < 35 (oversold),
             Stochastic %K < 20 and %K crosses above %D,
             Volume spike confirms reversal

  SELL when: Price reaches Middle Band (mean) OR Upper Band,
             RSI > 65 (overbought),
             Stochastic %K > 80 and %K crosses below %D

WHY THIS WORKS:
  - Stocks revert to their mean ~70% of the time
  - Multiple oversold confirmations filter bad trades
  - Great for range-bound / sideways markets
  - Complements the Momentum strategy (different market conditions)
"""

import logging
import pandas as pd
import numpy as np

logger = logging.getLogger("alpharaghu.strategy.mean_reversion")


class MeanReversionStrategy:
    name = "mean_reversion"
    display_name = "🔄 Mean Reversion (BB+RSI)"

    def __init__(self,
                 bb_period: int = 20,
                 bb_std: float = 2.0,
                 rsi_period: int = 14,
                 rsi_oversold: float = 35,
                 rsi_overbought: float = 65,
                 stoch_k: int = 14,
                 stoch_d: int = 3):
        self.bb_period      = bb_period
        self.bb_std         = bb_std
        self.rsi_period     = rsi_period
        self.rsi_oversold   = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.stoch_k        = stoch_k
        self.stoch_d        = stoch_d

    # ── Indicators ───────────────────────────────────────────
    def _calc_bollinger(self, prices: pd.Series):
        sma    = prices.rolling(self.bb_period).mean()
        std    = prices.rolling(self.bb_period).std()
        upper  = sma + (std * self.bb_std)
        lower  = sma - (std * self.bb_std)
        width  = (upper - lower) / sma  # Bandwidth
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
        """Average True Range for dynamic stop placement"""
        high, low, close = df["high"], df["low"], df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    # ── Signal Generation ────────────────────────────────────
    def generate_signal(self, df: pd.DataFrame) -> dict:
        min_required = max(self.bb_period, self.rsi_period, self.stoch_k) + 20
        if len(df) < min_required:
            return self._no_signal("Not enough data")

        close  = df["close"]
        volume = df["volume"]

        upper_bb, mid_bb, lower_bb, bb_width = self._calc_bollinger(close)
        rsi                = self._calc_rsi(close)
        stoch_k, stoch_d   = self._calc_stochastic(df)
        atr                = self._calc_atr(df)
        avg_vol            = volume.rolling(20).mean()

        # Latest values
        price   = close.iloc[-1]
        rsi_now = rsi.iloc[-1]
        rsi_prev= rsi.iloc[-2]
        k_now   = stoch_k.iloc[-1]
        k_prev  = stoch_k.iloc[-2]
        d_now   = stoch_d.iloc[-1]
        d_prev  = stoch_d.iloc[-2]
        upper   = upper_bb.iloc[-1]
        mid     = mid_bb.iloc[-1]
        lower   = lower_bb.iloc[-1]
        width   = bb_width.iloc[-1]
        atr_val = atr.iloc[-1]
        vol_ratio = volume.iloc[-1] / avg_vol.iloc[-1] if avg_vol.iloc[-1] else 1

        # Squeeze detection (narrow bands = breakout coming, avoid mean reversion)
        in_squeeze = width < 0.02  # Bands very tight

        indicators = {
            "price":      round(price, 2),
            "rsi":        round(rsi_now, 2),
            "stoch_k":    round(k_now, 2),
            "stoch_d":    round(d_now, 2),
            "bb_upper":   round(upper, 2),
            "bb_mid":     round(mid, 2),
            "bb_lower":   round(lower, 2),
            "bb_width":   round(width * 100, 2),
            "atr":        round(atr_val, 3),
            "vol_ratio":  round(vol_ratio, 2),
        }

        if in_squeeze:
            return self._no_signal("BB squeeze detected - skipping mean reversion")

        # ── BUY (Oversold Bounce) ─────────────────────────────
        price_at_lower  = price <= lower * 1.005          # At or below lower band
        rsi_oversold    = rsi_now < self.rsi_oversold
        stoch_oversold  = k_now < 25
        stoch_k_cross_up = k_prev < d_prev and k_now >= d_now  # %K crosses %D from below
        rsi_turning_up  = rsi_now > rsi_prev

        buy_score = sum([
            price_at_lower   * 3.0,
            rsi_oversold     * 2.0,
            stoch_oversold   * 1.5,
            stoch_k_cross_up * 2.0,
            rsi_turning_up   * 1.0,
            (vol_ratio > 1.3) * 0.5,
        ])
        buy_max = 10.0

        # ── SELL (Overbought / Mean Target) ───────────────────
        price_at_upper     = price >= upper * 0.995
        price_at_mid       = price >= mid * 0.998         # Reached mean target
        rsi_overbought     = rsi_now > self.rsi_overbought
        stoch_overbought   = k_now > 75
        stoch_k_cross_down = k_prev > d_prev and k_now <= d_now

        sell_score = sum([
            price_at_upper     * 3.0,
            price_at_mid       * 1.5,
            rsi_overbought     * 2.0,
            stoch_overbought   * 1.5,
            stoch_k_cross_down * 2.0,
        ])
        sell_max = 10.0

        buy_strength  = buy_score  / buy_max
        sell_strength = sell_score / sell_max

        if buy_strength >= 0.55 and buy_strength > sell_strength:
            reasons = []
            if price_at_lower:    reasons.append(f"price at Lower BB ({lower:.2f})")
            if rsi_oversold:      reasons.append(f"RSI oversold ({rsi_now:.1f})")
            if stoch_k_cross_up:  reasons.append(f"Stoch %K crossover ({k_now:.1f})")
            if rsi_turning_up:    reasons.append("RSI turning up")
            return {
                "signal": "BUY",
                "strength": round(buy_strength, 2),
                "reason": " | ".join(reasons),
                "indicators": indicators,
                "targets": {
                    "entry":       round(price, 2),
                    "target":      round(mid, 2),         # Exit at mean
                    "stop":        round(price - 2 * atr_val, 2),
                }
            }

        elif sell_strength >= 0.55 and sell_strength > buy_strength:
            reasons = []
            if price_at_upper:       reasons.append(f"price at Upper BB ({upper:.2f})")
            if price_at_mid:         reasons.append(f"reached mean ({mid:.2f})")
            if rsi_overbought:       reasons.append(f"RSI overbought ({rsi_now:.1f})")
            if stoch_k_cross_down:   reasons.append(f"Stoch %K bearish ({k_now:.1f})")
            return {
                "signal": "SELL",
                "strength": round(sell_strength, 2),
                "reason": " | ".join(reasons),
                "indicators": indicators
            }

        return self._no_signal(
            f"In band | RSI:{rsi_now:.1f} | K:{k_now:.1f} | "
            f"Buy:{buy_strength:.0%} Sell:{sell_strength:.0%}"
        )

    def _no_signal(self, reason: str) -> dict:
        return {"signal": "HOLD", "strength": 0.0, "reason": reason, "indicators": {}}
