"""
ALPHARAGHU - Trading Dashboard v2.0
Streamlit + Plotly interactive dashboard
Run: streamlit run dashboard.py
"""
import sys, os, importlib.util, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))

# ── Plotly ────────────────────────────────────────────────────
try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ── Page Config ───────────────────────────────────────────────
st.set_page_config(
    page_title="ALPHARAGHU",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Design tokens ─────────────────────────────────────────────
C = {
    "bg":       "#0a0a0f",
    "card":     "#0f0f1a",
    "border":   "#1e1e3a",
    "green":    "#00ff88",
    "red":      "#ff4466",
    "blue":     "#58a6ff",
    "yellow":   "#f0c040",
    "orange":   "#ff9500",
    "text":     "#e8e8f0",
    "subtext":  "#6666aa",
    "grid":     "#1a1a2e",
}

# ── CSS ───────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap');
* {{ font-family: 'Syne', sans-serif; }}
code, .mono {{ font-family: 'Space Mono', monospace !important; }}
[data-testid="stAppViewContainer"] {{ background: {C['bg']}; color: {C['text']}; }}
[data-testid="stSidebar"] {{ background: {C['card']} !important; border-right: 1px solid {C['border']}; }}
.metric-card {{
    background: {C['card']}; border: 1px solid {C['border']};
    border-radius: 8px; padding: 20px; margin: 4px 0;
}}
.metric-value {{ font-size: 2rem; font-weight: 800; font-family: 'Space Mono', monospace; }}
.metric-label {{ font-size: 0.75rem; letter-spacing: 0.15em; text-transform: uppercase; color: {C['subtext']}; margin-bottom: 4px; }}
.signal-buy  {{ color: {C['green']}; border-left: 3px solid {C['green']}; padding-left: 10px; }}
.signal-sell {{ color: {C['red']};   border-left: 3px solid {C['red']};   padding-left: 10px; }}
.signal-hold {{ color: {C['subtext']}; border-left: 3px solid {C['border']}; padding-left: 10px; }}
.status-on  {{ background:{C['green']}20; color:{C['green']}; border:1px solid {C['green']}; border-radius:20px; padding:4px 14px; font-size:0.8rem; }}
.status-off {{ background:{C['red']}20;   color:{C['red']};   border:1px solid {C['red']};   border-radius:20px; padding:4px 14px; font-size:0.8rem; }}
.pos-card {{
    background:{C['card']}; border:1px solid {C['border']};
    border-radius:6px; padding:14px; margin:6px 0;
}}
.perf-win  {{ color:{C['green']}; }}
.perf-loss {{ color:{C['red']}; }}
h1, h2, h3 {{ font-family:'Syne',sans-serif; font-weight:800; }}
.stButton > button {{
    background:{C['card']}; color:{C['text']}; border:1px solid {C['border']};
    border-radius:6px; font-family:'Space Mono',monospace; font-size:0.8rem;
    width:100%; padding:10px; transition:all 0.2s;
}}
.stButton > button:hover {{ background:#2a2a50; border-color:{C['green']}; color:{C['green']}; }}
div[data-testid="stMetric"] {{
    background:{C['card']}; border:1px solid {C['border']}; border-radius:8px; padding:16px;
}}
div[data-testid="stMetric"] label {{ color:{C['subtext']} !important; font-size:0.75rem; letter-spacing:0.1em; text-transform:uppercase; }}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {{ color:{C['text']}; font-family:'Space Mono',monospace; font-size:1.6rem; }}
.stDataFrame {{ border:1px solid {C['border']}; border-radius:6px; }}
.backtest-metric {{
    background:{C['card']}; border:1px solid {C['border']};
    border-radius:8px; padding:16px; text-align:center; margin:4px;
}}
</style>
""", unsafe_allow_html=True)

# ── Plotly dark theme ─────────────────────────────────────────
PLOTLY_LAYOUT = dict(
    template="plotly_dark",
    plot_bgcolor=C["bg"],
    paper_bgcolor=C["card"],
    font=dict(color=C["text"], family="Space Mono, monospace", size=11),
    xaxis=dict(gridcolor=C["grid"], linecolor=C["border"], showgrid=True),
    yaxis=dict(gridcolor=C["grid"], linecolor=C["border"], showgrid=True),
    margin=dict(l=50, r=20, t=40, b=40),
    legend=dict(bgcolor=C["card"], bordercolor=C["border"], borderwidth=1),
)

def styled_fig(fig, title: str = "", height: int = 350):
    fig.update_layout(**PLOTLY_LAYOUT, title=title, height=height,
                      title_font=dict(size=13, color=C["subtext"]))
    return fig


# ── Module Loader ─────────────────────────────────────────────
def load_module(name, *parts):
    path = os.path.join(ROOT, *parts)
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

@st.cache_resource(ttl=60)
def load_alpaca():
    try:
        cfg = load_module("config_d", "config.py")
        am  = load_module("alpaca_d", "broker", "alpaca_client.py")
        return am.AlpacaClient(), cfg
    except Exception as e:
        return None, None

# ── File helpers ──────────────────────────────────────────────
STATE_FILE  = os.path.join(ROOT, "logs", "bot_state.json")
SIGNAL_LOG  = os.path.join(ROOT, "logs", "signals.json")

def get_bot_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"running": False, "started_at": None}

def set_bot_state(running: bool):
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    state = {"running": running,
             "started_at": datetime.now().isoformat() if running else None}
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def get_recent_signals():
    try:
        if os.path.exists(SIGNAL_LOG):
            with open(SIGNAL_LOG) as f:
                return json.load(f)
    except Exception:
        pass
    return []

def get_log_tail(n=100):
    # Try dated log first, then fallback
    from glob import glob
    log_dir = os.path.join(ROOT, "logs")
    dated   = sorted(glob(os.path.join(log_dir, "alpharaghu_*.log")), reverse=True)
    path    = dated[0] if dated else os.path.join(log_dir, "alpharaghu.log")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception:
        return "No log file found yet."

@st.cache_resource(ttl=300)
def load_db():
    try:
        mod = load_module("trade_db_d", "utils", "trade_database.py")
        return mod.TradeDatabase()
    except Exception:
        return None

# ── Plotly Charts ─────────────────────────────────────────────
def chart_equity_curve(db, height=320, mini=False):
    """Portfolio equity curve from portfolio_snapshots table."""
    if not HAS_PLOTLY or db is None:
        return None
    try:
        import sqlite3
        db_path = os.path.join(ROOT, "data", "trades.db")
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql_query(
                "SELECT timestamp, portfolio_value FROM portfolio_snapshots "
                "ORDER BY timestamp ASC", conn
            )
        if df.empty or len(df) < 2:
            return None
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        start_val = df["portfolio_value"].iloc[0]
        df["pct_return"] = (df["portfolio_value"] - start_val) / start_val * 100

        fig = go.Figure()
        color = C["green"] if df["portfolio_value"].iloc[-1] >= start_val else C["red"]
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["portfolio_value"],
            mode="lines",
            line=dict(color=color, width=2),
            fill="tozeroy",
            fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)",
            name="Portfolio",
            hovertemplate="<b>%{y:$,.2f}</b><br>%{x}<extra></extra>",
        ))
        if not mini:
            # Add start-value reference line
            fig.add_hline(y=start_val, line_dash="dot",
                          line_color=C["subtext"], line_width=1,
                          annotation_text="Start", annotation_font_color=C["subtext"])
        title = "" if mini else "Portfolio Equity Curve"
        return styled_fig(fig, title, height)
    except Exception:
        return None


def chart_drawdown(db, height=200):
    """Drawdown % chart from portfolio_snapshots."""
    if not HAS_PLOTLY or db is None:
        return None
    try:
        import sqlite3
        db_path = os.path.join(ROOT, "data", "trades.db")
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql_query(
                "SELECT timestamp, portfolio_value FROM portfolio_snapshots "
                "ORDER BY timestamp ASC", conn
            )
        if df.empty or len(df) < 2:
            return None
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        vals        = df["portfolio_value"]
        peak        = vals.cummax()
        drawdown_pct = ((vals - peak) / peak * 100).fillna(0)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=drawdown_pct,
            mode="lines", fill="tozeroy",
            line=dict(color=C["red"], width=1.5),
            fillcolor=f"rgba(255,68,102,0.15)",
            name="Drawdown",
            hovertemplate="<b>%{y:.2f}%</b><br>%{x}<extra></extra>",
        ))
        return styled_fig(fig, "Drawdown from Peak (%)", height)
    except Exception:
        return None


def chart_pnl_histogram(trades_df, height=280):
    """P&L distribution histogram."""
    if not HAS_PLOTLY or trades_df is None or trades_df.empty:
        return None
    if "pnl" not in trades_df.columns:
        return None
    pnl = trades_df["pnl"].dropna()
    if len(pnl) < 2:
        return None

    colors = [C["green"] if v >= 0 else C["red"] for v in pnl]
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=pnl,
        nbinsx=20,
        marker_color=[C["green"] if v >= 0 else C["red"] for v in pnl],
        marker_line_color=C["border"],
        marker_line_width=1,
        name="P&L",
        hovertemplate="P&L: $%{x:.2f}<br>Count: %{y}<extra></extra>",
    ))
    fig.add_vline(x=0, line_dash="dash", line_color=C["subtext"], line_width=1)
    return styled_fig(fig, "P&L Distribution ($)", height)


def chart_pnl_by_symbol(trades_df, height=300):
    """Bar chart — total P&L per symbol."""
    if not HAS_PLOTLY or trades_df is None or trades_df.empty:
        return None
    if "pnl" not in trades_df.columns or "symbol" not in trades_df.columns:
        return None
    grouped = trades_df.groupby("symbol")["pnl"].sum().sort_values()
    if grouped.empty:
        return None

    colors = [C["green"] if v >= 0 else C["red"] for v in grouped.values]
    fig = go.Figure(go.Bar(
        x=grouped.index.tolist(),
        y=grouped.values.tolist(),
        marker_color=colors,
        marker_line_color=C["border"],
        marker_line_width=1,
        hovertemplate="%{x}<br><b>$%{y:.2f}</b><extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dot", line_color=C["subtext"], line_width=1)
    return styled_fig(fig, "Total P&L by Symbol ($)", height)


def chart_win_loss_donut(perf: dict, height=260):
    """Win/loss donut."""
    if not HAS_PLOTLY:
        return None
    wins   = perf.get("wins", 0)
    losses = perf.get("losses", 0)
    if wins + losses == 0:
        return None
    fig = go.Figure(go.Pie(
        labels=["Wins", "Losses"],
        values=[wins, losses],
        hole=0.6,
        marker_colors=[C["green"], C["red"]],
        marker_line=dict(color=C["border"], width=2),
        textinfo="percent",
        hovertemplate="%{label}: %{value} trades (%{percent})<extra></extra>",
    ))
    fig.add_annotation(
        text=f"{perf.get('win_rate', 0):.0f}%",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=22, color=C["text"], family="Space Mono"),
    )
    return styled_fig(fig, "Win Rate", height)


def chart_monthly_pnl(trades_df, height=280):
    """Monthly P&L heatmap bar chart."""
    if not HAS_PLOTLY or trades_df is None or trades_df.empty:
        return None
    if "pnl" not in trades_df.columns or "exit_time" not in trades_df.columns:
        return None
    try:
        df = trades_df.copy()
        df["exit_time"] = pd.to_datetime(df["exit_time"])
        df["month"] = df["exit_time"].dt.to_period("M").astype(str)
        monthly = df.groupby("month")["pnl"].sum().sort_index()
        if monthly.empty:
            return None
        colors = [C["green"] if v >= 0 else C["red"] for v in monthly.values]
        fig = go.Figure(go.Bar(
            x=monthly.index.tolist(),
            y=monthly.values.tolist(),
            marker_color=colors,
            marker_line_color=C["border"],
            marker_line_width=1,
            hovertemplate="%{x}<br><b>$%{y:,.2f}</b><extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="dot", line_color=C["subtext"], line_width=1)
        return styled_fig(fig, "Monthly P&L ($)", height)
    except Exception:
        return None


def chart_backtest_equity(result: dict, height=380):
    """Backtest equity curve vs buy-and-hold."""
    if not HAS_PLOTLY:
        return None
    dates = result.get("dates", [])
    eq    = result.get("equity_curve", [])
    bah   = result.get("bah_curve", [])
    if not dates or not eq:
        return None

    # Align lengths
    n = min(len(dates), len(eq))
    dates = dates[:n]; eq = eq[:n]
    bah_n = min(len(bah), n)
    bah   = bah[:bah_n]
    while len(bah) < n:
        bah.insert(0, eq[0])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=eq,
        mode="lines", name="Strategy",
        line=dict(color=C["green"], width=2.5),
        hovertemplate="<b>Strategy: $%{y:,.2f}</b><br>%{x}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=dates, y=bah,
        mode="lines", name="Buy & Hold",
        line=dict(color=C["subtext"], width=1.5, dash="dash"),
        hovertemplate="<b>B&H: $%{y:,.2f}</b><br>%{x}<extra></extra>",
    ))
    return styled_fig(fig, f"Backtest Equity Curve — {result.get('symbol', '')} "
                          f"({result.get('period', '')})", height)


def chart_backtest_drawdown(result: dict, height=200):
    """Backtest drawdown."""
    if not HAS_PLOTLY:
        return None
    dates = result.get("dates", [])[:len(result.get("drawdown", []))]
    dd    = result.get("drawdown", [])
    if not dates or not dd:
        return None
    fig = go.Figure(go.Scatter(
        x=dates, y=dd, mode="lines", fill="tozeroy",
        line=dict(color=C["red"], width=1.5),
        fillcolor="rgba(255,68,102,0.15)",
        hovertemplate="<b>%{y:.2f}%</b><br>%{x}<extra></extra>",
    ))
    return styled_fig(fig, "Backtest Drawdown (%)", height)


# ── Sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ALPHARAGHU")
    st.markdown("---")

    state = get_bot_state()
    if state["running"]:
        st.markdown('<span class="status-on">● RUNNING</span>', unsafe_allow_html=True)
        if state.get("started_at"):
            st.caption(f"Since {state['started_at'][:16]}")
    else:
        st.markdown('<span class="status-off">● STOPPED</span>', unsafe_allow_html=True)

    st.markdown("")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶ START"):
            set_bot_state(True)
            st.success("Started!"); st.rerun()
    with col2:
        if st.button("■ STOP"):
            set_bot_state(False)
            st.warning("Stopped!"); st.rerun()

    st.markdown("---")
    page = st.radio("", ["Dashboard", "Positions", "Signals",
                         "Performance", "Backtest", "Live Log"],
                    label_visibility="hidden")
    st.markdown("---")
    auto_refresh = st.toggle("Auto Refresh (30s)", value=True)
    if st.button("⟳ Refresh Now"):
        st.rerun()
    st.markdown("---")
    st.caption("ALPHARAGHU v4.0  •  Plotly + pandas-ta")
    st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")


# ── Load shared resources ─────────────────────────────────────
client, cfg = load_alpaca()
db          = load_db()


# ════════════════════════════════════════════════════════════════
# PAGE: Dashboard
# ════════════════════════════════════════════════════════════════
if page == "Dashboard":
    st.markdown("# ALPHARAGHU")
    st.markdown("##### Algorithmic Trading Dashboard")
    st.markdown("---")

    if client:
        try:
            acct      = client.get_account()
            portfolio = float(acct.portfolio_value)
            cash      = float(acct.cash)
            equity    = float(acct.equity)
            pl_day    = equity - float(acct.last_equity)
            pl_pct    = (pl_day / float(acct.last_equity)) * 100 if float(acct.last_equity) else 0
            buying_pw = float(acct.buying_power)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Portfolio Value", f"${portfolio:,.2f}")
            c2.metric("Day P&L",         f"${pl_day:+,.2f}", f"{pl_pct:+.2f}%")
            c3.metric("Cash",            f"${cash:,.2f}")
            c4.metric("Buying Power",    f"${buying_pw:,.2f}")

            st.markdown("")

            # ── Mini equity curve ──────────────────────────────
            if db:
                mini_fig = chart_equity_curve(db, height=200, mini=True)
                if mini_fig:
                    st.plotly_chart(mini_fig, use_container_width=True,
                                   config={"displayModeBar": False})

            # ── Positions + Account Status ─────────────────────
            positions = client.get_positions()
            col_left, col_right = st.columns([3, 2])

            with col_left:
                st.markdown("### Open Positions")
                if positions:
                    pos_data = []
                    for p in positions:
                        pl   = float(p.unrealized_pl)
                        plpc = float(p.unrealized_plpc) * 100
                        pos_data.append({
                            "Symbol":   p.symbol,
                            "Qty":      float(p.qty),
                            "Entry":    f"${float(p.avg_entry_price):.2f}",
                            "Current":  f"${float(p.current_price):.2f}",
                            "P&L ($)":  f"${pl:+.2f}",
                            "P&L (%)":  f"{plpc:+.2f}%",
                            "Value":    f"${float(p.market_value):,.2f}",
                        })
                    st.dataframe(pd.DataFrame(pos_data),
                                 use_container_width=True, hide_index=True)
                else:
                    st.info("No open positions")

            with col_right:
                st.markdown("### Account Status")
                max_pos = getattr(cfg, "MAX_OPEN_POSITIONS", 0) if cfg else 0
                max_str = "∞" if max_pos == 0 else str(max_pos)
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Open Positions</div>
                    <div class="metric-value">{len(positions)}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Max Positions</div>
                    <div class="metric-value">{max_str}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Scan Interval</div>
                    <div class="metric-value">{getattr(cfg,'SCAN_INTERVAL_MINUTES',15) if cfg else 15}m</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Risk / Trade</div>
                    <div class="metric-value">{getattr(cfg,'RISK_PER_TRADE_PCT',2) if cfg else 2}%</div>
                </div>
                """, unsafe_allow_html=True)

        except Exception as e:
            st.error(f"Error loading account: {e}")
    else:
        st.warning("Not connected to Alpaca. Check your .env file.")


# ════════════════════════════════════════════════════════════════
# PAGE: Positions
# ════════════════════════════════════════════════════════════════
elif page == "Positions":
    st.markdown("# Open Positions")
    st.markdown("<small style='color:#6666aa'>Shows ALL positions including manually placed trades</small>",
                unsafe_allow_html=True)
    st.markdown("---")

    if client:
        try:
            positions = client.get_positions()
            if not positions:
                st.info("No open positions right now.")
            else:
                total_pl  = sum(float(p.unrealized_pl) for p in positions)
                total_val = sum(float(p.market_value)  for p in positions)
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Positions",   len(positions))
                c2.metric("Total Market Value", f"${total_val:,.2f}")
                sign = "+" if total_pl >= 0 else ""
                c3.metric("Total Unrealized P&L", f"${sign}{total_pl:.2f}")
                st.markdown("")

                for p in positions:
                    pl   = float(p.unrealized_pl)
                    plpc = float(p.unrealized_plpc) * 100
                    color = C["green"] if pl >= 0 else C["red"]
                    sign2 = "+" if pl >= 0 else ""
                    st.markdown(f"""
                    <div class="pos-card">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div>
                                <span style="font-size:1.4rem;font-weight:800;font-family:'Space Mono'">{p.symbol}</span>
                                <span style="color:{C['subtext']};margin-left:12px;font-size:0.85rem">{float(p.qty):.0f} shares</span>
                            </div>
                            <div style="text-align:right;">
                                <span style="color:{color};font-family:'Space Mono';font-size:1.2rem;font-weight:700">{sign2}${pl:.2f}</span>
                                <span style="color:{color};margin-left:8px;font-size:0.85rem">({sign2}{plpc:.2f}%)</span>
                            </div>
                        </div>
                        <div style="display:flex;gap:24px;margin-top:10px;color:{C['subtext']};font-size:0.82rem">
                            <span>Avg Entry: <b style="color:{C['text']}">${float(p.avg_entry_price):.2f}</b></span>
                            <span>Current: <b style="color:{C['text']}">${float(p.current_price):.2f}</b></span>
                            <span>Market Value: <b style="color:{C['text']}">${float(p.market_value):,.2f}</b></span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                st.markdown("---")
                st.markdown("### Close Positions")
                cols = st.columns(min(len(positions), 5))
                for i, p in enumerate(positions):
                    with cols[i % 5]:
                        if st.button(f"✕ {p.symbol}"):
                            client.close_position(p.symbol)
                            st.success(f"Closed {p.symbol}")
                            time.sleep(1); st.rerun()

        except Exception as e:
            st.error(f"Error: {e}")


# ════════════════════════════════════════════════════════════════
# PAGE: Signals
# ════════════════════════════════════════════════════════════════
elif page == "Signals":
    st.markdown("# Signal Log")
    st.markdown("---")

    signals = get_recent_signals()
    if not signals:
        st.info("No signals logged yet.")
    else:
        # Stats bar
        buys  = [s for s in signals if s.get("signal") == "BUY"]
        sells = [s for s in signals if s.get("signal") == "SELL"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Signals", len(signals))
        c2.metric("BUY Signals",   len(buys))
        c3.metric("SELL Signals",  len(sells))
        st.markdown("")

        for sig in reversed(signals[-30:]):
            signal_type = sig.get("signal", "HOLD")
            css_class   = {"BUY": "signal-buy", "SELL": "signal-sell"}.get(signal_type, "signal-hold")
            conf        = sig.get("confidence", 0)
            conf_pct    = f"{conf:.0%}" if isinstance(conf, float) and conf < 1 else f"{conf}%"
            st.markdown(f"""
            <div class="{css_class}" style="margin:8px 0;padding:12px;background:{C['card']};border-radius:6px;">
                <div style="display:flex;justify-content:space-between">
                    <b style="font-size:1.1rem">{sig.get('symbol','?')} — {signal_type}</b>
                    <span style="color:{C['subtext']};font-size:0.8rem">{sig.get('time','')}</span>
                </div>
                <div style="color:{C['subtext']};margin-top:6px;font-size:0.85rem">
                    Confidence: {conf_pct} | Consensus: {sig.get('consensus',0)}/3
                </div>
                <div style="color:{C['subtext']};font-size:0.8rem;margin-top:4px">{sig.get('reason','')}</div>
            </div>
            """, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════
# PAGE: Performance  (full Plotly upgrade)
# ════════════════════════════════════════════════════════════════
elif page == "Performance":
    st.markdown("# Performance & Analytics")
    st.markdown("---")

    try:
        if db is None:
            st.error("Database not available")
        else:
            perf   = db.get_performance()
            trades = db.get_recent_trades(200)
            trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

            if perf.get("total_trades", 0) == 0:
                st.info("No completed trades yet. Performance analytics appear once trades are closed.")
            else:
                # ── Top metrics ──────────────────────────────────
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Total Trades",   perf["total_trades"])
                c2.metric("Win Rate",       f"{perf['win_rate']}%")
                c3.metric("Profit Factor",  perf["profit_factor"])
                c4.metric("Total P&L",      f"${perf['total_pnl']:+,.2f}")
                c5.metric("Best Trade",     f"${perf['best_trade']:+,.2f}")

                st.markdown("")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Avg Win",      f"${perf['avg_win']:+,.2f}")
                c2.metric("Avg Loss",     f"-${perf['avg_loss']:,.2f}")
                c3.metric("Wins",         perf["wins"])
                c4.metric("Losses",       perf["losses"])

                st.markdown("---")

                # ── Equity curve + drawdown ───────────────────────
                eq_fig = chart_equity_curve(db, height=300)
                if eq_fig:
                    st.plotly_chart(eq_fig, use_container_width=True,
                                    config={"displayModeBar": True})
                else:
                    st.info("Equity curve: not enough portfolio snapshots yet.")

                dd_fig = chart_drawdown(db, height=180)
                if dd_fig:
                    st.plotly_chart(dd_fig, use_container_width=True,
                                    config={"displayModeBar": False})

                st.markdown("---")

                # ── P&L charts row ────────────────────────────────
                col_a, col_b, col_c = st.columns(3)

                with col_a:
                    donut = chart_win_loss_donut(perf)
                    if donut:
                        st.plotly_chart(donut, use_container_width=True,
                                        config={"displayModeBar": False})

                with col_b:
                    hist_fig = chart_pnl_histogram(trades_df)
                    if hist_fig:
                        st.plotly_chart(hist_fig, use_container_width=True,
                                        config={"displayModeBar": False})

                with col_c:
                    sym_fig = chart_pnl_by_symbol(trades_df)
                    if sym_fig:
                        st.plotly_chart(sym_fig, use_container_width=True,
                                        config={"displayModeBar": False})

                # ── Monthly P&L ───────────────────────────────────
                monthly_fig = chart_monthly_pnl(trades_df)
                if monthly_fig:
                    st.markdown("---")
                    st.plotly_chart(monthly_fig, use_container_width=True,
                                    config={"displayModeBar": False})

                # ── Trade table ───────────────────────────────────
                st.markdown("---")
                st.markdown("### Trade History")
                if not trades_df.empty:
                    display_cols = [c for c in
                        ["symbol","side","qty","entry_price","exit_price",
                         "pnl","pnl_pct","exit_reason","entry_time","exit_time"]
                        if c in trades_df.columns]
                    show_df = trades_df[display_cols].copy()
                    # Colour pnl column
                    st.dataframe(show_df, use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Performance error: {e}")

    # ── Risk Status ───────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Risk Status")
    try:
        rm_mod  = load_module("risk_mod_d", "utils", "risk_manager.py")
        fresh_c, _ = load_alpaca()
        if fresh_c:
            rm     = rm_mod.RiskManager(fresh_c)
            status = rm.get_status()
            c1, c2, c3 = st.columns(3)
            c1.metric("Drawdown from Peak", f"{status['drawdown_pct']:.1f}%")
            c2.metric("Day P&L %",          f"{status['daily_pnl_pct']:+.1f}%")
            halted = status["halted"]
            color  = C["red"] if halted else C["green"]
            label  = "HALTED" if halted else "ACTIVE"
            c3.markdown(
                f"<div style='padding:16px;background:{C['card']};border:1px solid {color};"
                f"border-radius:8px'><div style='color:{C['subtext']};font-size:0.75rem;"
                f"text-transform:uppercase'>Bot Status</div>"
                f"<div style='color:{color};font-size:1.4rem;font-weight:800'>{label}</div></div>",
                unsafe_allow_html=True
            )
    except Exception as e:
        st.warning(f"Risk status unavailable: {e}")


# ════════════════════════════════════════════════════════════════
# PAGE: Backtest  (new)
# ════════════════════════════════════════════════════════════════
elif page == "Backtest":
    st.markdown("# Strategy Backtester")
    st.markdown(
        "<small style='color:#6666aa'>Tests the ALPHARAGHU Momentum strategy on historical daily data "
        "via yfinance. Answers: does this strategy actually work on a given symbol?</small>",
        unsafe_allow_html=True
    )
    st.markdown("---")

    # ── Controls ──────────────────────────────────────────────
    col_sym, col_per, col_cap, col_stop = st.columns(4)
    with col_sym:
        symbol = st.text_input("Symbol", value="AAPL",
                               help="Any US stock ticker").upper().strip()
    with col_per:
        period = st.selectbox("Period", ["1y", "2y", "3y", "5y"], index=1,
                              help="Historical data range from yfinance")
    with col_cap:
        capital = st.number_input("Starting Capital ($)", value=10000,
                                  min_value=1000, step=1000)
    with col_stop:
        stop_pct = st.slider("Stop Loss (%)", min_value=1.0, max_value=8.0,
                             value=3.0, step=0.5) / 100

    run_col, _ = st.columns([1, 3])
    with run_col:
        run_bt = st.button("▶ Run Backtest", type="primary")

    if run_bt:
        if not symbol:
            st.error("Enter a symbol first")
        else:
            with st.spinner(f"Fetching {period} of data for {symbol} and running backtest…"):
                try:
                    bt_mod = load_module("backtester_d", "utils", "backtester.py")
                    bt     = bt_mod.Backtester()
                    result = bt.run(symbol=symbol, period=period,
                                    initial_capital=float(capital),
                                    stop_pct=stop_pct)
                    st.session_state["bt_result"] = result
                    st.success(f"Backtest complete — {result['metrics']['total_trades']} trades found")
                except ImportError as e:
                    st.error(f"Missing dependency: {e}")
                    st.info("Run: pip install yfinance")
                except Exception as e:
                    st.error(f"Backtest error: {e}")

    # ── Results ───────────────────────────────────────────────
    result = st.session_state.get("bt_result")
    if result:
        m = result["metrics"]
        st.markdown("---")
        st.markdown(f"### Results — {result['symbol']} ({result['period']})")

        # Metric cards
        alpha_color = C["green"] if m["alpha"] >= 0 else C["red"]
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        c1.metric("Total Return",    f"{m['total_return']:+.1f}%",
                  delta=f"α {m['alpha']:+.1f}% vs B&H")
        c2.metric("Buy & Hold",      f"{m['bah_return']:+.1f}%")
        c3.metric("Sharpe Ratio",    f"{m['sharpe']:.2f}",
                  delta="Good >1.0" if m['sharpe'] >= 1 else "Below 1.0")
        c4.metric("Max Drawdown",    f"{m['max_drawdown']:.1f}%")
        c5.metric("Win Rate",        f"{m['win_rate']:.0f}%")
        c6.metric("Profit Factor",   f"{m['profit_factor']:.2f}",
                  delta="Good >1.5" if m['profit_factor'] >= 1.5 else "Below 1.5")

        st.markdown("")
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        c1.metric("Total Trades",   m["total_trades"])
        c2.metric("Wins",           m["wins"])
        c3.metric("Losses",         m["losses"])
        c4.metric("Avg Win",        f"{m['avg_win_pct']:+.1f}%")
        c5.metric("Avg Loss",       f"{m['avg_loss_pct']:.1f}%")
        c6.metric("Avg Hold",       f"{m['avg_bars_held']:.0f} days")

        st.markdown("")
        c1, c2 = st.columns(2)
        c1.metric("Final Capital",   f"${m['final_capital']:,.2f}")
        c2.metric("Calmar Ratio",    f"{m['calmar']:.2f}",
                  delta="Good >1.0" if m['calmar'] >= 1 else None)

        st.markdown("---")

        # Equity curve
        eq_fig = chart_backtest_equity(result, height=380)
        if eq_fig:
            st.plotly_chart(eq_fig, use_container_width=True)

        # Drawdown
        dd_fig = chart_backtest_drawdown(result, height=200)
        if dd_fig:
            st.plotly_chart(dd_fig, use_container_width=True,
                            config={"displayModeBar": False})

        # Trade list
        st.markdown("---")
        st.markdown("### Individual Trades")
        if result["trades"]:
            trades_df = pd.DataFrame(result["trades"])
            # Style: green/red pnl
            st.dataframe(trades_df, use_container_width=True, hide_index=True)

            # Download button
            csv = trades_df.to_csv(index=False)
            st.download_button(
                label="⬇ Download trades CSV",
                data=csv,
                file_name=f"backtest_{result['symbol']}_{result['period']}.csv",
                mime="text/csv",
            )
        else:
            st.info("No trades found in this period with current strategy settings.")

        # Verdict
        st.markdown("---")
        st.markdown("### Verdict")
        verdict_items = []
        if m["total_return"] > m["bah_return"]:
            verdict_items.append(f"✅ Strategy outperforms buy-and-hold by **{m['alpha']:+.1f}%**")
        else:
            verdict_items.append(f"❌ Strategy underperforms buy-and-hold by **{abs(m['alpha']):.1f}%**")
        if m["sharpe"] >= 1.5:
            verdict_items.append(f"✅ Sharpe {m['sharpe']:.2f} — excellent risk-adjusted returns")
        elif m["sharpe"] >= 0.8:
            verdict_items.append(f"✅ Sharpe {m['sharpe']:.2f} — acceptable")
        else:
            verdict_items.append(f"⚠️ Sharpe {m['sharpe']:.2f} — consider tightening entry rules")
        if m["win_rate"] >= 55:
            verdict_items.append(f"✅ Win rate {m['win_rate']:.0f}% — majority of trades profitable")
        else:
            verdict_items.append(f"⚠️ Win rate {m['win_rate']:.0f}% — needs higher avg win vs avg loss")
        if m["max_drawdown"] >= -20:
            verdict_items.append(f"✅ Max drawdown {m['max_drawdown']:.1f}% — within acceptable range")
        else:
            verdict_items.append(f"⚠️ Max drawdown {m['max_drawdown']:.1f}% — consider tighter stops")
        for item in verdict_items:
            st.markdown(item)


# ════════════════════════════════════════════════════════════════
# PAGE: Live Log
# ════════════════════════════════════════════════════════════════
elif page == "Live Log":
    st.markdown("# Live Log")
    st.markdown("<small style='color:#6666aa'>Shows latest 100 lines from today's loguru log file</small>",
                unsafe_allow_html=True)
    st.markdown("---")

    log_text = get_log_tail(100)

    # Colour-code the log text
    lines = log_text.split("\n")
    colored = []
    for line in lines:
        if "ERROR" in line or "CRITICAL" in line:
            colored.append(f'<span style="color:{C["red"]}">{line}</span>')
        elif "WARNING" in line or "WARN" in line:
            colored.append(f'<span style="color:{C["yellow"]}">{line}</span>')
        elif "BUY FILLED" in line:
            colored.append(f'<span style="color:{C["green"]};font-weight:bold">{line}</span>')
        elif "TRAIL STOP" in line or "SELL FILLED" in line:
            colored.append(f'<span style="color:{C["red"]};font-weight:bold">{line}</span>')
        elif "SECTOR-SCAN" in line or "SECTOR" in line:
            colored.append(f'<span style="color:{C["blue"]}">{line}</span>')
        elif ": BUY |" in line:
            colored.append(f'<span style="color:{C["green"]}">{line}</span>')
        elif ": SELL |" in line:
            colored.append(f'<span style="color:{C["orange"]}">{line}</span>')
        else:
            colored.append(f'<span style="color:{C["subtext"]}">{line}</span>')

    html_log = (
        f"<div style='background:{C['card']};border:1px solid {C['border']};"
        f"border-radius:8px;padding:16px;font-family:Space Mono,monospace;"
        f"font-size:0.78rem;line-height:1.6;max-height:600px;overflow-y:auto'>"
        + "<br>".join(colored)
        + "</div>"
    )
    st.markdown(html_log, unsafe_allow_html=True)

    if st.button("⟳ Refresh Log"):
        st.rerun()


# ── Auto Refresh ──────────────────────────────────────────────
if auto_refresh and page != "Backtest":
    time.sleep(30)
    st.rerun()
