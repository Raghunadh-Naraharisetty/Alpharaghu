"""
ALPHARAGHU - Streamlit Trading Dashboard
Run with: streamlit run dashboard.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta
import importlib.util
import json

ROOT = os.path.dirname(os.path.abspath(__file__))

# ── Page Config ──────────────────────────────────────────────
st.set_page_config(
    page_title="ALPHARAGHU Trading",
    page_icon="A",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap');

* { font-family: 'Syne', sans-serif; }
code, .mono { font-family: 'Space Mono', monospace !important; }

[data-testid="stAppViewContainer"] {
    background: #0a0a0f;
    color: #e8e8f0;
}
[data-testid="stSidebar"] {
    background: #0f0f1a !important;
    border-right: 1px solid #1e1e3a;
}
.metric-card {
    background: #0f0f1a;
    border: 1px solid #1e1e3a;
    border-radius: 8px;
    padding: 20px;
    margin: 4px 0;
}
.metric-value {
    font-size: 2rem;
    font-weight: 800;
    font-family: 'Space Mono', monospace;
}
.metric-label {
    font-size: 0.75rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #6666aa;
    margin-bottom: 4px;
}
.signal-buy  { color: #00ff88; border-left: 3px solid #00ff88; padding-left: 10px; }
.signal-sell { color: #ff4466; border-left: 3px solid #ff4466; padding-left: 10px; }
.signal-hold { color: #6666aa; border-left: 3px solid #3a3a5a; padding-left: 10px; }
.status-pill-on  { background:#00ff8820; color:#00ff88; border:1px solid #00ff88; border-radius:20px; padding:4px 14px; font-size:0.8rem; }
.status-pill-off { background:#ff446620; color:#ff4466; border:1px solid #ff4466; border-radius:20px; padding:4px 14px; font-size:0.8rem; }
.pos-card {
    background: #0f0f1a;
    border: 1px solid #1e1e3a;
    border-radius: 6px;
    padding: 14px;
    margin: 6px 0;
}
h1, h2, h3 { font-family: 'Syne', sans-serif; font-weight: 800; }
.stButton > button {
    background: #1e1e3a;
    color: #e8e8f0;
    border: 1px solid #3a3a6a;
    border-radius: 6px;
    font-family: 'Space Mono', monospace;
    font-size: 0.8rem;
    width: 100%;
    padding: 10px;
    transition: all 0.2s;
}
.stButton > button:hover { background: #2a2a50; border-color: #00ff88; color: #00ff88; }
div[data-testid="stMetric"] {
    background: #0f0f1a;
    border: 1px solid #1e1e3a;
    border-radius: 8px;
    padding: 16px;
}
div[data-testid="stMetric"] label { color: #6666aa !important; font-size: 0.75rem; letter-spacing: 0.1em; text-transform: uppercase; }
div[data-testid="stMetric"] [data-testid="stMetricValue"] { color: #e8e8f0; font-family: 'Space Mono', monospace; font-size: 1.6rem; }
.stDataFrame { border: 1px solid #1e1e3a; border-radius: 6px; }
</style>
""", unsafe_allow_html=True)


# ── Module Loader ────────────────────────────────────────────
def load_alpaca():
    def load_module(name, *parts):
        path = os.path.join(ROOT, *parts)
        spec = importlib.util.spec_from_file_location(name, path)
        mod  = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    try:
        cfg = load_module("config", "config.py")
        am  = load_module("alpaca_client", "broker", "alpaca_client.py")
        return am.AlpacaClient(), cfg
    except Exception as e:
        st.error(f"Failed to connect: {e}")
        return None, None


# ── State File (bot on/off) ───────────────────────────────────
STATE_FILE = os.path.join(ROOT, "logs", "bot_state.json")
SIGNAL_LOG = os.path.join(ROOT, "logs", "signals.json")

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
    state = {"running": running, "started_at": datetime.now().isoformat() if running else None}
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

def get_log_tail(n=50):
    log_path = os.path.join(ROOT, "logs", "alpharaghu.log")
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception:
        return "No log file found yet."


# ── Load Alpaca ───────────────────────────────────────────────
client, cfg = load_alpaca()


# ── Sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ALPHARAGHU")
    st.markdown("---")

    # Bot State
    state = get_bot_state()
    if state["running"]:
        st.markdown('<span class="status-pill-on">RUNNING</span>', unsafe_allow_html=True)
        if state.get("started_at"):
            st.caption(f"Since {state['started_at'][:16]}")
    else:
        st.markdown('<span class="status-pill-off">STOPPED</span>', unsafe_allow_html=True)

    st.markdown("")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("START"):
            set_bot_state(True)
            st.success("Bot started!")
            st.rerun()
    with col2:
        if st.button("STOP"):
            set_bot_state(False)
            st.warning("Bot stopped!")
            st.rerun()

    st.markdown("---")

    # Navigation
    page = st.radio("", ["Dashboard", "Positions", "Signals", "Performance", "Live Log"], label_visibility="hidden")

    st.markdown("---")

    # Auto-refresh
    auto_refresh = st.toggle("Auto Refresh (30s)", value=True)
    if st.button("Refresh Now"):
        st.rerun()

    st.markdown("---")
    st.caption("ALPHARAGHU v1.0")
    st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")


# ── Main Content ──────────────────────────────────────────────

if page == "Dashboard":
    st.markdown("# ALPHARAGHU")
    st.markdown("##### Algorithmic Trading Dashboard")
    st.markdown("---")

    if client:
        try:
            acct = client.get_account()
            portfolio = float(acct.portfolio_value)
            cash      = float(acct.cash)
            equity    = float(acct.equity)
            pl_day    = equity - float(acct.last_equity)
            pl_pct    = (pl_day / float(acct.last_equity)) * 100 if float(acct.last_equity) else 0
            buying_pw = float(acct.buying_power)

            # Metrics row
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Portfolio Value",  f"${portfolio:,.2f}")
            c2.metric("Day P&L",          f"${pl_day:+,.2f}", f"{pl_pct:+.2f}%")
            c3.metric("Cash",             f"${cash:,.2f}")
            c4.metric("Buying Power",     f"${buying_pw:,.2f}")

            st.markdown("")

            # Positions — fetch fresh every time (shows manual trades too)
            fresh_client, _ = load_alpaca()
            positions = fresh_client.get_positions() if fresh_client else client.get_positions()
            col_left, col_right = st.columns([3, 2])

            with col_left:
                st.markdown("### Open Positions")
                if positions:
                    pos_data = []
                    for p in positions:
                        pl   = float(p.unrealized_pl)
                        plpc = float(p.unrealized_plpc) * 100
                        pos_data.append({
                            "Symbol":  p.symbol,
                            "Qty":     float(p.qty),
                            "Avg Entry": f"${float(p.avg_entry_price):.2f}",
                            "Current": f"${float(p.current_price):.2f}",
                            "P&L ($)": f"${pl:+.2f}",
                            "P&L (%)": f"{plpc:+.2f}%",
                            "Market Value": f"${float(p.market_value):,.2f}",
                        })
                    df = pd.DataFrame(pos_data)
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.info("No open positions")

            with col_right:
                st.markdown("### Account Status")
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Open Positions</div>
                    <div class="metric-value">{len(positions)}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Max Allowed</div>
                    <div class="metric-value">{cfg.MAX_OPEN_POSITIONS}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Scan Interval</div>
                    <div class="metric-value">{cfg.SCAN_INTERVAL_MINUTES}m</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Risk / Trade</div>
                    <div class="metric-value">{cfg.RISK_PER_TRADE_PCT}%</div>
                </div>
                """, unsafe_allow_html=True)

        except Exception as e:
            st.error(f"Error loading account data: {e}")
    else:
        st.warning("Not connected to Alpaca. Check your .env file.")


elif page == "Positions":
    st.markdown("# Open Positions")
    st.markdown("<small style='color:#6666aa'>Shows ALL positions — including manually placed trades</small>",
                unsafe_allow_html=True)
    st.markdown("---")

    if client:
        try:
            # Always fetch fresh — no caching
            client2, _ = load_alpaca()
            positions = client2.get_positions() if client2 else client.get_positions()

            if not positions:
                st.info("No open positions right now. Manually placed trades appear here too.")
            else:
                total_pl = sum(float(p.unrealized_pl) for p in positions)
                total_val = sum(float(p.market_value) for p in positions)
                sign = "+" if total_pl >= 0 else ""
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Positions", len(positions))
                col2.metric("Total Market Value", f"${total_val:,.2f}")
                col3.metric("Total Unrealized P&L", f"${sign}{total_pl:.2f}")
                st.markdown("")

                for p in positions:
                    pl   = float(p.unrealized_pl)
                    plpc = float(p.unrealized_plpc) * 100
                    color = "#00ff88" if pl >= 0 else "#ff4466"
                    sign2 = "+" if pl >= 0 else ""
                    st.markdown(f"""
                    <div class="pos-card">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div>
                                <span style="font-size:1.4rem; font-weight:800; font-family:'Space Mono'">{p.symbol}</span>
                                <span style="color:#6666aa; margin-left:12px; font-size:0.85rem">{float(p.qty):.0f} shares</span>
                            </div>
                            <div style="text-align:right;">
                                <span style="color:{color}; font-family:'Space Mono'; font-size:1.2rem; font-weight:700">{sign2}${pl:.2f}</span>
                                <span style="color:{color}; margin-left:8px; font-size:0.85rem">({sign2}{plpc:.2f}%)</span>
                            </div>
                        </div>
                        <div style="display:flex; gap:24px; margin-top:10px; color:#6666aa; font-size:0.82rem">
                            <span>Avg Entry: <b style="color:#e8e8f0">${float(p.avg_entry_price):.2f}</b></span>
                            <span>Current:   <b style="color:#e8e8f0">${float(p.current_price):.2f}</b></span>
                            <span>Mkt Value: <b style="color:#e8e8f0">${float(p.market_value):,.2f}</b></span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                st.markdown("---")
                st.markdown("### Close Positions")
                cols = st.columns(min(len(positions), 4))
                for i, p in enumerate(positions):
                    with cols[i % 4]:
                        if st.button(f"CLOSE {p.symbol}"):
                            client.close_position(p.symbol)
                            st.success(f"Closed {p.symbol}")
                            time.sleep(1)
                            st.rerun()

        except Exception as e:
            st.error(f"Error loading positions: {e}")
            st.info("Try clicking Refresh Now in the sidebar.")


elif page == "Signals":
    st.markdown("# Signal Log")
    st.markdown("---")

    signals = get_recent_signals()
    if not signals:
        st.info("No signals logged yet. Signals appear here when the bot finds trades during market hours.")
    else:
        for sig in reversed(signals[-30:]):
            signal_type = sig.get("signal", "HOLD")
            color_class = {"BUY": "signal-buy", "SELL": "signal-sell"}.get(signal_type, "signal-hold")
            st.markdown(f"""
            <div class="{color_class}" style="margin: 8px 0; padding: 12px; background:#0f0f1a; border-radius:6px;">
                <div style="display:flex; justify-content:space-between">
                    <b style="font-size:1.1rem">{sig.get('symbol','?')} — {signal_type}</b>
                    <span style="color:#6666aa; font-size:0.8rem">{sig.get('time','')}</span>
                </div>
                <div style="color:#aaaacc; margin-top:6px; font-size:0.85rem">
                    Confidence: {sig.get('confidence', 0):.0%} | Consensus: {sig.get('consensus', 0)}/3
                </div>
                <div style="color:#6666aa; font-size:0.8rem; margin-top:4px">{sig.get('reason', '')}</div>
            </div>
            """, unsafe_allow_html=True)


elif page == "Performance":
    st.markdown("# Performance & Risk")
    st.markdown("---")

    # Load database
    import importlib.util as _ilu, sys as _sys
    try:
        _spec = _ilu.spec_from_file_location("trade_db2",
                    os.path.join(ROOT, "utils", "trade_database.py"))
        _mod = _ilu.module_from_spec(_spec)
        _sys.modules["trade_db2"] = _mod
        _spec.loader.exec_module(_mod)
        db = _mod.TradeDatabase()
        perf   = db.get_performance()
        trades = db.get_recent_trades(50)

        if perf.get("total_trades", 0) == 0:
            st.info("No completed trades yet. Performance stats appear here once trades are closed.")
        else:
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Total Trades",   perf["total_trades"])
            c2.metric("Win Rate",       f"{perf['win_rate']}%")
            c3.metric("Profit Factor",  perf["profit_factor"])
            c4.metric("Total P&L",      f"${perf['total_pnl']:+,.2f}")

            st.markdown("")
            c1,c2 = st.columns(2)
            c1.metric("Avg Win",   f"${perf['avg_win']:+,.2f}")
            c2.metric("Avg Loss",  f"-${perf['avg_loss']:,.2f}")

            st.markdown("---")
            st.markdown("### Recent Trades")
            if trades:
                import pandas as pd
                df = pd.DataFrame(trades)
                display_cols = [c for c in
                    ["symbol","side","qty","entry_price","exit_price",
                     "pnl","pnl_pct","exit_reason","entry_time"]
                    if c in df.columns]
                st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Could not load trade database: {e}")

    # Risk status
    st.markdown("---")
    st.markdown("### Risk Status")
    try:
        _spec2 = _ilu.spec_from_file_location("risk_mod2",
                     os.path.join(ROOT, "utils", "risk_manager.py"))
        _rmod = _ilu.module_from_spec(_spec2)
        _sys.modules["risk_mod2"] = _rmod
        _spec2.loader.exec_module(_rmod)
        fresh_client, _cfg = load_alpaca()
        if fresh_client:
            rm     = _rmod.RiskManager(fresh_client)
            status = rm.get_status()
            c1,c2,c3 = st.columns(3)
            c1.metric("Drawdown from Peak", f"{status['drawdown_pct']:.1f}%")
            c2.metric("Day P&L %",          f"{status['daily_pnl_pct']:+.1f}%")
            halted = status["halted"]
            c3.markdown(
                f"<div style='padding:16px;background:#0f0f1a;border:1px solid "
                f"{'#ff4466' if halted else '#00ff88'};border-radius:8px'>"
                f"<div style='color:#6666aa;font-size:0.75rem;text-transform:uppercase'>Bot Status</div>"
                f"<div style='color:{'#ff4466' if halted else '#00ff88'};font-size:1.4rem;font-weight:800'>"
                f"{'HALTED' if halted else 'ACTIVE'}</div></div>",
                unsafe_allow_html=True
            )
            if status["trailing_active"]:
                st.info(f"Trailing stops active: {', '.join(status['trailing_active'])}")
    except Exception as e:
        st.warning(f"Risk status unavailable: {e}")

elif page == "Live Log":
    st.markdown("# Live Log")
    st.markdown("---")
    log_text = get_log_tail(100)
    st.code(log_text, language="text")
    if st.button("Refresh Log"):
        st.rerun()


# ── Auto Refresh ─────────────────────────────────────────────
if auto_refresh:
    time.sleep(30)
    st.rerun()
