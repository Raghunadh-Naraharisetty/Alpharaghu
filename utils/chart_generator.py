"""
ALPHARAGHU - Chart Generator
=============================
Generates a dark-theme candlestick chart every time a BUY signal fires
and sends it to Telegram so you can visually review the setup instantly.

Chart includes:
  · 5-minute OHLCV candlesticks (last 6.5 hours = full session)
  · EMA 9 (yellow) and EMA 21 (blue)
  · VWAP line (white dashed)
  · Volume bars colored by candle direction
  · Entry price (gold ▲), Stop-Loss (red --), Take-Profit (green --)
  · Signal time marked with vertical line
  · Title shows symbol, confidence, strategies, time

No external dependencies beyond matplotlib + numpy (already installed).
"""

import io
import logging
import os
import sys
from datetime import datetime

logger = logging.getLogger("alpharaghu.chart")

# ── Matplotlib setup (non-interactive backend — required for servers) ─────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.gridspec as gridspec
    import matplotlib.ticker as mticker
    import matplotlib.dates as mdates
    import numpy as np
    _MPL_OK = True
except ImportError:
    _MPL_OK = False
    logger.warning("[CHART] matplotlib not available — charts disabled")


# ── Color palette (TradingView dark theme) ────────────────────────────────────
BG       = "#0d1117"
PANEL    = "#161b22"
BORDER   = "#30363d"
TEXT     = "#e6edf3"
MUTED    = "#8b949e"
GREEN    = "#3fb950"
RED      = "#f85149"
YELLOW   = "#f0c040"
BLUE     = "#58a6ff"
WHITE    = "#ffffff"
PURPLE   = "#bc8cff"


def _ema(values: list, span: int) -> list:
    """Simple EMA calculation without pandas dependency."""
    k = 2 / (span + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _vwap(highs, lows, closes, volumes) -> list:
    """Intraday VWAP — resets each session."""
    tp        = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    cum_tpv   = 0.0
    cum_vol   = 0.0
    result    = []
    for t, v in zip(tp, volumes):
        cum_tpv += t * v
        cum_vol += v
        result.append(cum_tpv / cum_vol if cum_vol > 0 else t)
    return result


def generate_chart(
    symbol: str,
    bars: list,          # list of dicts: {timestamp, open, high, low, close, volume}
    entry:  float,
    stop:   float,
    target: float,
    confidence: float,
    consensus:  int,
    signal_time: str = "",
) -> bytes | None:
    """
    Build the chart image and return raw PNG bytes.
    Returns None if matplotlib is unavailable or bars are insufficient.

    Args:
        bars: list of OHLCV dicts from alpaca_client.get_bars()
        entry/stop/target: prices from the signal
        confidence: 0-1 float
        consensus: int (e.g. 2 = "2/3 strategies")
        signal_time: HH:MM string for the title
    """
    if not _MPL_OK:
        return None

    if not bars or len(bars) < 10:
        logger.warning(f"[CHART] {symbol}: only {len(bars)} bars — skipping chart")
        return None

    try:
        # ── Unpack bars ───────────────────────────────────────────────────────
        opens   = [float(b["open"])   for b in bars]
        highs   = [float(b["high"])   for b in bars]
        lows    = [float(b["low"])    for b in bars]
        closes  = [float(b["close"])  for b in bars]
        volumes = [float(b["volume"]) for b in bars]
        n       = len(bars)
        xs      = list(range(n))

        # Build time labels for x-axis (every 30 bars ≈ 2.5 hrs on 5-min chart)
        timestamps = [b.get("timestamp", b.get("time", "")) for b in bars]

        # ── Indicators ───────────────────────────────────────────────────────
        ema9  = _ema(closes, 9)
        ema21 = _ema(closes, 21)
        vwap  = _vwap(highs, lows, closes, volumes)

        # ── Figure layout ─────────────────────────────────────────────────────
        fig = plt.figure(figsize=(13, 7.5), facecolor=BG, dpi=110)
        gs  = gridspec.GridSpec(
            2, 1, height_ratios=[4.5, 1], hspace=0.0,
            top=0.92, bottom=0.08, left=0.07, right=0.88
        )
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1], sharex=ax1)

        for ax in [ax1, ax2]:
            ax.set_facecolor(BG)
            ax.tick_params(colors=MUTED, labelsize=8)
            for spine in ax.spines.values():
                spine.set_color(BORDER)
            ax.grid(True, color=BORDER, linewidth=0.4, linestyle="-", alpha=0.5)

        # ── Candlesticks ──────────────────────────────────────────────────────
        for i in xs:
            up    = closes[i] >= opens[i]
            color = GREEN if up else RED
            body_bot = min(opens[i], closes[i])
            body_h   = max(abs(closes[i] - opens[i]), 0.005)

            ax1.add_patch(mpatches.Rectangle(
                (i - 0.35, body_bot), 0.7, body_h,
                color=color, zorder=3
            ))
            ax1.plot([i, i], [lows[i], highs[i]],
                     color=color, lw=0.9, zorder=2)

        # ── Indicators ───────────────────────────────────────────────────────
        ax1.plot(xs, ema9,  color=YELLOW, lw=1.3, label="EMA 9",  zorder=4, alpha=0.9)
        ax1.plot(xs, ema21, color=BLUE,   lw=1.3, label="EMA 21", zorder=4, alpha=0.9)
        ax1.plot(xs, vwap,  color=WHITE,  lw=1.0, label="VWAP",   zorder=4,
                 alpha=0.7, linestyle="--")

        # ── Entry / Stop / Target lines ───────────────────────────────────────
        right_pad = n + 3   # where to write the labels

        # Stop Loss (red)
        ax1.axhline(stop,   color=RED,    lw=1.1, ls="--", alpha=0.85, zorder=5)
        ax1.text(right_pad, stop,   f" SL ${stop:.2f}",
                 color=RED,    fontsize=8, va="center", fontweight="bold")

        # Entry (gold)
        ax1.axhline(entry,  color=YELLOW, lw=1.2, ls="--", alpha=0.85, zorder=5)
        ax1.text(right_pad, entry,  f" EP ${entry:.2f}",
                 color=YELLOW, fontsize=8, va="center", fontweight="bold")

        # Take Profit (green)
        ax1.axhline(target, color=GREEN,  lw=1.1, ls="--", alpha=0.85, zorder=5)
        ax1.text(right_pad, target, f" TP ${target:.2f}",
                 color=GREEN,  fontsize=8, va="center", fontweight="bold")

        # Entry arrow on the last candle
        ax1.scatter(
            [n - 1], [closes[-1]],
            marker="^", color=YELLOW, s=100, zorder=6
        )

        # R:R ratio annotation
        risk   = abs(entry - stop)
        reward = abs(target - entry)
        rr     = reward / risk if risk > 0 else 0
        ax1.text(
            0.01, 0.97,
            f"R:R  1:{rr:.1f}   Risk ${risk:.2f}   Reward ${reward:.2f}",
            transform=ax1.transAxes,
            color=MUTED, fontsize=8, va="top",
            bbox=dict(facecolor=PANEL, edgecolor=BORDER, boxstyle="round,pad=0.3")
        )

        # ── Price axis ────────────────────────────────────────────────────────
        price_range  = max(highs) - min(lows)
        ax1.set_ylim(min(lows) - price_range * 0.05, max(highs) + price_range * 0.15)
        ax1.set_xlim(-1, n + 12)
        ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter("$%.2f"))
        ax1.yaxis.tick_right()
        ax1.tick_params(axis="y", colors=MUTED, labelsize=8, right=True, left=False)
        ax1.tick_params(axis="x", which="both", bottom=False, labelbottom=False)

        # Legend
        ax1.legend(
            loc="upper left", facecolor=PANEL,
            edgecolor=BORDER, labelcolor=TEXT,
            fontsize=8, framealpha=0.9
        )

        # ── Volume bars ───────────────────────────────────────────────────────
        vol_colors = [GREEN if closes[i] >= opens[i] else RED for i in xs]
        ax2.bar(xs, volumes, color=vol_colors, alpha=0.55, width=0.8)
        ax2.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f"{x/1e6:.1f}M" if x >= 1e6 else f"{x/1e3:.0f}K")
        )
        ax2.yaxis.tick_right()
        ax2.tick_params(axis="y", colors=MUTED, labelsize=7, right=True, left=False)
        ax2.tick_params(axis="x", colors=MUTED, labelsize=7)
        ax2.set_xlim(-1, n + 12)

        # X-axis time labels — every ~13 bars (≈ 65 min on 5-min chart)
        tick_step = max(1, n // 7)
        tick_xs   = list(range(0, n, tick_step))
        tick_lbls = []
        for ti in tick_xs:
            ts = timestamps[ti] if ti < len(timestamps) else ""
            if ts:
                try:
                    # Parse ISO timestamp from Alpaca
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    tick_lbls.append(dt.strftime("%H:%M"))
                except Exception:
                    tick_lbls.append(str(ts)[-5:])
            else:
                tick_lbls.append("")
        ax2.set_xticks(tick_xs)
        ax2.set_xticklabels(tick_lbls, color=MUTED)

        # ── Title ─────────────────────────────────────────────────────────────
        title = (
            f"{symbol}  ·  5m  ·  📈 BUY {confidence:.0%}  {consensus}/3 strategies"
            + (f"  ·  {signal_time}" if signal_time else "")
        )
        fig.suptitle(title, color=TEXT, fontsize=12, fontweight="bold", y=0.97)

        # ── Watermark ─────────────────────────────────────────────────────────
        fig.text(
            0.01, 0.01, "ALPHARAGHU",
            color=BORDER, fontsize=8, alpha=0.7
        )

        # ── Export to bytes ───────────────────────────────────────────────────
        buf = io.BytesIO()
        plt.savefig(
            buf, format="png", dpi=120,
            facecolor=BG, bbox_inches="tight"
        )
        buf.seek(0)
        png_bytes = buf.read()
        plt.close(fig)

        logger.info(
            f"[CHART] {symbol}: generated {len(png_bytes)//1024}KB chart "
            f"({n} bars, EP=${entry:.2f} SL=${stop:.2f} TP=${target:.2f})"
        )
        return png_bytes

    except Exception as e:
        logger.error(f"[CHART] Error generating chart for {symbol}: {e}")
        try:
            plt.close("all")
        except Exception:
            pass
        return None
