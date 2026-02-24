"""
ALPHARAGHU - Backtester
=======================
Pure pandas/numpy vectorized backtester — no external dependencies beyond
what's already in requirements.txt.

Runs the momentum strategy (EMA + RSI + MACD + ADX if available) on
historical daily OHLCV data fetched via yfinance and produces:

  - Trade-by-trade list with entry/exit dates, prices, P&L
  - Full equity curve (capital over time)
  - Performance metrics: Sharpe, max drawdown, win rate, profit factor
  - Buy-and-hold comparison

Usage (standalone):
    from utils.backtester import Backtester
    bt = Backtester()
    result = bt.run("AAPL", period="2y")
    print(result["metrics"])

Usage (from dashboard backtest page):
    result = bt.run(symbol, period, initial_capital)
    # result["equity_curve"] → list of floats for Plotly
    # result["trades"]       → list of dicts for DataFrame table
    # result["metrics"]      → dict of performance stats
"""

import logging
import pandas as pd
import numpy as np
from datetime import datetime

logger = logging.getLogger("alpharaghu.backtester")

# Optional enhancements
try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False
    logger.warning("[backtest] yfinance not installed. Install with: pip install yfinance")


class Backtester:
    """
    Vectorized backtester for ALPHARAGHU momentum strategy.
    Uses daily OHLCV data — yfinance provides 2+ years free.
    """

    # ── Data Fetching ─────────────────────────────────────────
    def fetch_data(self, symbol: str, period: str = "2y") -> pd.DataFrame:
        """Fetch historical daily OHLCV from yfinance."""
        if not HAS_YFINANCE:
            raise ImportError("yfinance required: pip install yfinance")
        try:
            ticker = yf.Ticker(symbol)
            df     = ticker.history(period=period, interval="1d", auto_adjust=True)
            if df.empty:
                raise ValueError(f"No data returned for {symbol}")
            df.columns = [c.lower() for c in df.columns]
            df = df[["open", "high", "low", "close", "volume"]].copy()
            df.index = pd.to_datetime(df.index)
            if df.index.tz is not None:
                df.index = df.index.tz_convert(None)
            df.dropna(inplace=True)
            logger.info(f"[backtest] {symbol}: {len(df)} daily bars ({period})")
            return df
        except Exception as e:
            logger.error(f"[backtest] Data fetch error for {symbol}: {e}")
            raise

    # ── Indicator Calculations ────────────────────────────────
    def _rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        delta    = prices.diff()
        gain     = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
        loss     = (-delta.clip(upper=0)).ewm(com=period - 1, min_periods=period).mean()
        rs       = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def _macd(self, prices: pd.Series, fast=12, slow=26, signal=9):
        ema_fast  = prices.ewm(span=fast,   adjust=False).mean()
        ema_slow  = prices.ewm(span=slow,   adjust=False).mean()
        macd_line = ema_fast - ema_slow
        sig_line  = macd_line.ewm(span=signal, adjust=False).mean()
        return macd_line, sig_line

    def _ema(self, prices: pd.Series, period: int) -> pd.Series:
        return prices.ewm(span=period, adjust=False).mean()

    def _adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """ADX from pandas-ta if available, else constant 30 (assume trending)."""
        if HAS_PANDAS_TA:
            try:
                adx_df = ta.adx(df["high"], df["low"], df["close"], length=period)
                if adx_df is not None:
                    col = f"ADX_{period}"
                    if col in adx_df.columns:
                        return adx_df[col].fillna(25.0)
            except Exception:
                pass
        return pd.Series(30.0, index=df.index)

    # ── Signal Generation ─────────────────────────────────────
    def _generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Vectorized signal generation. Returns df with added columns:
        'buy_signal' and 'sell_signal' (bool).
        """
        close  = df["close"]
        volume = df["volume"]

        rsi              = self._rsi(close)
        macd, macd_sig   = self._macd(close)
        ema200           = self._ema(close, 200)
        ema50            = self._ema(close, 50)
        avg_vol          = volume.rolling(20).mean()
        adx              = self._adx(df)

        # Vectorized condition flags (shifted to avoid look-ahead bias)
        above_ema200     = close > ema200
        rsi_cross_up     = (rsi.shift(1) < 52) & (rsi >= 48)
        macd_cross_up    = (macd.shift(1) < macd_sig.shift(1)) & (macd >= macd_sig)
        volume_spike     = volume > avg_vol * 1.3
        adx_trending     = adx >= 20
        rsi_not_overbought = rsi < 75

        # ── BUY: need EMA + RSI cross + MACD cross + volume + ADX ──
        df["buy_signal"] = (
            above_ema200 &
            rsi_cross_up &
            macd_cross_up &
            volume_spike &
            adx_trending &
            rsi_not_overbought
        )

        # ── SELL / EXIT conditions ────────────────────────────
        below_ema200    = close < ema200
        rsi_cross_down  = (rsi.shift(1) > 48) & (rsi <= 52)
        macd_cross_down = (macd.shift(1) > macd_sig.shift(1)) & (macd <= macd_sig)
        rsi_overbought  = rsi > 75

        df["sell_signal"] = (
            (below_ema200 & rsi_cross_down) |
            (macd_cross_down & below_ema200) |
            rsi_overbought
        )

        return df

    # ── Trade Simulation ──────────────────────────────────────
    def _simulate_trades(self, df: pd.DataFrame,
                         initial_capital: float,
                         stop_pct: float = 0.03,
                         risk_per_trade: float = 0.95) -> tuple:
        """
        Simulate trades from signals. Applies:
        - Entry on next bar open after signal (no look-ahead)
        - Stop-loss at entry * (1 - stop_pct)
        - Exit on sell signal or stop hit

        Returns (trades list, equity_curve list, dates list).
        """
        trades        = []
        equity_curve  = [initial_capital]
        dates         = [df.index[0]]
        capital       = initial_capital
        in_position   = False
        entry_price   = 0.0
        entry_date    = None
        stop_price    = 0.0

        for i in range(201, len(df)):
            row         = df.iloc[i]
            prev        = df.iloc[i - 1]
            price       = row["close"]
            bar_date    = df.index[i]

            if not in_position:
                # Buy on next bar open after signal
                if prev["buy_signal"]:
                    entry_price = row["open"] if row["open"] > 0 else price
                    stop_price  = entry_price * (1 - stop_pct)
                    in_position = True
                    entry_date  = bar_date

            else:
                # Check stop-loss first (intra-bar)
                hit_stop = row["low"] <= stop_price
                # Check exit signal
                exit_sig = prev["sell_signal"] or hit_stop

                if exit_sig:
                    exit_price = stop_price if hit_stop else (
                        row["open"] if row["open"] > 0 else price
                    )
                    exit_reason = "stop_loss" if hit_stop else "signal_exit"
                    pnl_pct    = (exit_price - entry_price) / entry_price
                    position_value = capital * risk_per_trade
                    pnl_dollar     = pnl_pct * position_value
                    capital       += pnl_dollar

                    trades.append({
                        "entry_date":  entry_date.strftime("%Y-%m-%d"),
                        "exit_date":   bar_date.strftime("%Y-%m-%d"),
                        "entry_price": round(entry_price, 2),
                        "exit_price":  round(exit_price, 2),
                        "pnl_pct":     round(pnl_pct * 100, 2),
                        "pnl_dollar":  round(pnl_dollar, 2),
                        "win":         pnl_dollar > 0,
                        "reason":      exit_reason,
                        "bars_held":   i - df.index.get_loc(entry_date),
                    })
                    in_position = False
                    entry_price = 0.0

            equity_curve.append(max(capital, 1.0))
            dates.append(bar_date)

        return trades, equity_curve, dates

    # ── Performance Metrics ───────────────────────────────────
    def _calc_metrics(self, trades: list, equity_curve: list,
                      initial_capital: float, df: pd.DataFrame) -> dict:
        """Calculate full suite of performance metrics."""
        eq = pd.Series(equity_curve)

        # Returns
        daily_returns = eq.pct_change().dropna()
        total_return  = (eq.iloc[-1] - initial_capital) / initial_capital * 100

        # Sharpe (annualized, daily returns)
        sharpe = 0.0
        if daily_returns.std() > 0:
            sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)

        # Max Drawdown
        rolling_max = eq.cummax()
        drawdown     = (eq - rolling_max) / rolling_max * 100
        max_drawdown = drawdown.min()

        # Calmar = total_return / abs(max_drawdown)
        calmar = total_return / abs(max_drawdown) if max_drawdown != 0 else 0.0

        # Win/Loss stats
        wins   = [t for t in trades if t["win"]]
        losses = [t for t in trades if not t["win"]]
        win_rate = len(wins) / max(len(trades), 1) * 100

        avg_win_pct  = np.mean([t["pnl_pct"] for t in wins])   if wins   else 0.0
        avg_loss_pct = np.mean([t["pnl_pct"] for t in losses]) if losses else 0.0

        gross_profit = sum(t["pnl_dollar"] for t in wins)
        gross_loss   = abs(sum(t["pnl_dollar"] for t in losses))
        profit_factor = gross_profit / max(gross_loss, 0.01)

        avg_bars = np.mean([t["bars_held"] for t in trades]) if trades else 0

        # Buy-and-hold comparison (from bar 200 onward)
        bah_start  = df["close"].iloc[200]
        bah_end    = df["close"].iloc[-1]
        bah_return = (bah_end - bah_start) / bah_start * 100

        return {
            "total_trades":    len(trades),
            "wins":            len(wins),
            "losses":          len(losses),
            "win_rate":        round(win_rate, 1),
            "total_return":    round(total_return, 2),
            "bah_return":      round(bah_return, 2),
            "alpha":           round(total_return - bah_return, 2),
            "sharpe":          round(sharpe, 2),
            "max_drawdown":    round(max_drawdown, 2),
            "calmar":          round(calmar, 2),
            "profit_factor":   round(profit_factor, 2),
            "avg_win_pct":     round(avg_win_pct, 2),
            "avg_loss_pct":    round(avg_loss_pct, 2),
            "avg_bars_held":   round(avg_bars, 1),
            "final_capital":   round(eq.iloc[-1], 2),
            "initial_capital": round(initial_capital, 2),
            "gross_profit":    round(gross_profit, 2),
            "gross_loss":      round(gross_loss, 2),
        }

    # ── Main Entry Point ──────────────────────────────────────
    def run(self, symbol: str, period: str = "2y",
            initial_capital: float = 10_000.0,
            stop_pct: float = 0.03) -> dict:
        """
        Run full backtest for a symbol.

        Args:
            symbol:          Stock ticker (e.g. "AAPL")
            period:          yfinance period string ("1y", "2y", "5y")
            initial_capital: Starting capital in USD
            stop_pct:        Stop-loss % below entry (default 3%)

        Returns dict with keys:
            trades:       list[dict]  — every trade with entry/exit/P&L
            equity_curve: list[float] — capital at every bar
            dates:        list[str]   — matching dates for equity_curve
            drawdown:     list[float] — drawdown % at every bar
            metrics:      dict        — performance stats
            bah_curve:    list[float] — buy-and-hold equity curve for comparison
        """
        logger.info(f"[backtest] Running {symbol} | period={period} | "
                    f"capital=${initial_capital:,.0f}")

        df = self.fetch_data(symbol, period)
        if len(df) < 220:
            raise ValueError(
                f"Need at least 220 bars for backtest. "
                f"{symbol} only has {len(df)} for period={period}. "
                f"Try a longer period."
            )

        df = self._generate_signals(df)
        trades, equity_curve, dates = self._simulate_trades(
            df, initial_capital, stop_pct
        )
        metrics = self._calc_metrics(trades, equity_curve, initial_capital, df)

        # Drawdown series
        eq = pd.Series(equity_curve)
        drawdown = ((eq - eq.cummax()) / eq.cummax() * 100).tolist()

        # Buy-and-hold curve (for comparison on same axes)
        bah_start = df["close"].iloc[200]
        bah_series = df["close"].iloc[200:].reset_index(drop=True)
        bah_curve  = (bah_series / bah_start * initial_capital).tolist()
        # Pad to match equity_curve length
        while len(bah_curve) < len(equity_curve):
            bah_curve.insert(0, initial_capital)

        date_strs = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime")
                     else str(d) for d in dates]

        logger.info(
            f"[backtest] {symbol} done — {metrics['total_trades']} trades | "
            f"Return: {metrics['total_return']:+.1f}% vs B&H {metrics['bah_return']:+.1f}% | "
            f"Sharpe: {metrics['sharpe']:.2f} | "
            f"MaxDD: {metrics['max_drawdown']:.1f}%"
        )

        return {
            "symbol":       symbol,
            "period":       period,
            "trades":       trades,
            "equity_curve": equity_curve,
            "dates":        date_strs,
            "drawdown":     drawdown,
            "bah_curve":    bah_curve,
            "metrics":      metrics,
        }
