"""
ALPHARAGHU - Trade Database (SQLite)
Saves every trade with full history for performance analysis
Inspired by friend's system — adapted for alpaca-py SDK
"""
import sqlite3, os, logging, pandas as pd
from datetime import datetime

logger  = logging.getLogger("alpharaghu.database")
ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "trades.db")


class TradeDatabase:
    def __init__(self):
        os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
        self._init_db()
        logger.info(f"[DB] Trade database ready")

    def _conn(self):
        return sqlite3.connect(DB_PATH)

    def _init_db(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY, symbol TEXT, side TEXT,
                qty REAL, entry_price REAL, exit_price REAL,
                entry_time TEXT, exit_time TEXT, pnl REAL, pnl_pct REAL,
                exit_reason TEXT, strategy TEXT, confidence REAL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT, signal TEXT, confidence REAL, consensus INTEGER,
                reason TEXT, acted INTEGER DEFAULT 0, timestamp TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                timestamp TEXT PRIMARY KEY, portfolio_value REAL,
                cash REAL, open_positions INTEGER, day_pnl REAL)""")

    def record_open(self, trade_id, symbol, side, qty, entry_price,
                    strategy="", confidence=0.0):
        with self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO trades
                (trade_id,symbol,side,qty,entry_price,entry_time,strategy,confidence)
                VALUES (?,?,?,?,?,?,?,?)""",
                (trade_id, symbol, side, qty, entry_price,
                 datetime.now().isoformat(), strategy, confidence))

    def record_close(self, trade_id, exit_price, exit_reason):
        with self._conn() as c:
            row = c.execute(
                "SELECT qty,entry_price,side FROM trades WHERE trade_id=?",
                (trade_id,)).fetchone()
            if not row:
                return None, None
            qty, entry, side = row
            pnl     = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
            pnl_pct = (pnl / (entry * qty)) * 100 if entry > 0 else 0
            c.execute("""UPDATE trades SET exit_price=?,exit_time=?,
                pnl=?,pnl_pct=?,exit_reason=? WHERE trade_id=?""",
                (exit_price, datetime.now().isoformat(),
                 pnl, pnl_pct, exit_reason, trade_id))
        return round(pnl, 2), round(pnl_pct, 2)

    def log_signal(self, symbol, signal, confidence, consensus, reason, acted=False):
        with self._conn() as c:
            c.execute("""INSERT INTO signals
                (symbol,signal,confidence,consensus,reason,acted,timestamp)
                VALUES (?,?,?,?,?,?,?)""",
                (symbol, signal, confidence, consensus, reason[:300],
                 1 if acted else 0, datetime.now().isoformat()))

    def snapshot_portfolio(self, portfolio_value, cash, open_positions, day_pnl):
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO portfolio_snapshots VALUES (?,?,?,?,?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M"),
                 portfolio_value, cash, open_positions, day_pnl))

    def get_performance(self):
        with self._conn() as c:
            df = pd.read_sql_query(
                "SELECT * FROM trades WHERE exit_price IS NOT NULL", c)
        if df.empty:
            return {"total_trades": 0, "message": "No completed trades yet"}
        winners = df[df["pnl"] > 0]
        losers  = df[df["pnl"] <= 0]
        avg_win  = winners["pnl"].mean() if len(winners) > 0 else 0
        avg_loss = abs(losers["pnl"].mean()) if len(losers) > 0 else 1
        pf = (avg_win * len(winners)) / (avg_loss * len(losers)) if len(losers) > 0 else 0
        return {
            "total_trades": len(df), "wins": len(winners), "losses": len(losers),
            "win_rate":      round(len(winners) / len(df) * 100, 1),
            "avg_win":       round(avg_win, 2), "avg_loss": round(avg_loss, 2),
            "profit_factor": round(pf, 2),  "total_pnl": round(df["pnl"].sum(), 2),
            "best_trade":    round(df["pnl"].max(), 2),
            "worst_trade":   round(df["pnl"].min(), 2),
        }

    def get_recent_trades(self, limit=20):
        with self._conn() as c:
            df = pd.read_sql_query(
                f"SELECT * FROM trades ORDER BY entry_time DESC LIMIT {limit}", c)
        return df.to_dict("records") if not df.empty else []
