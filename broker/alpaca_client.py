"""
ALPHARAGHU - Alpaca Broker Client
Uses the NEW official alpaca-py SDK (works on Windows/Mac/Linux)
pip install alpaca-py
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import pandas as pd

# ── New alpaca-py imports ─────────────────────────────────────
from alpaca.trading.client          import TradingClient
from alpaca.trading.requests        import (
    MarketOrderRequest,
    GetOrdersRequest,
    ClosePositionRequest,
)
from alpaca.trading.enums           import OrderSide, TimeInForce, OrderClass
from alpaca.data.historical         import StockHistoricalDataClient
from alpaca.data.requests           import (
    StockBarsRequest,
    StockSnapshotRequest,
    StockLatestQuoteRequest,
)
from alpaca.data.timeframe          import TimeFrame, TimeFrameUnit
from alpaca.common.exceptions       import APIError

import config

logger = logging.getLogger("alpharaghu.broker")

ET = ZoneInfo("America/New_York")


def _tf(timeframe_str: str) -> TimeFrame:
    """Convert string like '15Min' to alpaca-py TimeFrame object"""
    mapping = {
        "1Min":  TimeFrame(1,  TimeFrameUnit.Minute),
        "5Min":  TimeFrame(5,  TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "30Min": TimeFrame(30, TimeFrameUnit.Minute),
        "1Hour": TimeFrame(1,  TimeFrameUnit.Hour),
        "1Day":  TimeFrame(1,  TimeFrameUnit.Day),
    }
    return mapping.get(timeframe_str, TimeFrame(15, TimeFrameUnit.Minute))


class AlpacaClient:
    def __init__(self):
        paper = "paper" in config.ALPACA_BASE_URL.lower()

        # Trading client (orders, positions, account)
        self.trading = TradingClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
            paper=paper,
        )

        # Market data client (bars, quotes, snapshots)
        self.data = StockHistoricalDataClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
        )

        self._verify_connection()

    def _verify_connection(self):
        try:
            acct = self.trading.get_account()
            mode = "PAPER" if "paper" in config.ALPACA_BASE_URL.lower() else "LIVE"
            logger.info(f"[OK] Connected to Alpaca {mode} | Portfolio: ${float(acct.portfolio_value):,.2f}")
        except Exception as e:
            logger.error(f"[ERROR] Alpaca connection failed: {e}")
            raise

    # ── Account Info ────────────────────────────────────────
    def get_account(self):
        return self.trading.get_account()

    def get_portfolio_value(self) -> float:
        return float(self.trading.get_account().portfolio_value)

    def get_buying_power(self) -> float:
        return float(self.trading.get_account().buying_power)

    # ── Positions ───────────────────────────────────────────
    def get_positions(self) -> list:
        return self.trading.get_all_positions()

    def get_position(self, symbol: str):
        try:
            return self.trading.get_open_position(symbol)
        except Exception:
            return None

    def get_open_position_count(self) -> int:
        return len(self.trading.get_all_positions())

    # ── Orders ──────────────────────────────────────────────
    def place_market_order(self, symbol: str, qty: float, side: str,
                           stop_loss: float = None, take_profit: float = None):
        """
        Place a bracket market order (with stop loss + take profit).

        Alpaca rules we must follow:
          1. Bracket orders require WHOLE share quantities (no fractions)
          2. stop_price must be <= base_price - 0.01  (round DOWN)
          3. take_profit must be >= base_price + 0.01 (round UP)
        """
        import math
        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

            # ── Fix 1: Whole shares for bracket orders ────────
            # Alpaca rejects fractional qty with bracket/OCO orders
            whole_qty = max(1, int(qty))   # floor to whole number, minimum 1

            if stop_loss and take_profit:
                # ── Fix 2: Safe stop price (always round DOWN) ─
                # Must be at least $0.01 below base price
                safe_stop   = math.floor(stop_loss   * 100) / 100

                # ── Fix 3: Safe target price (always round UP) ─
                # Must be at least $0.01 above base price
                safe_target = math.ceil(take_profit  * 100) / 100

                logger.info(
                    f"[ORDER PREP] {symbol}: qty={whole_qty} "
                    f"stop=${safe_stop:.2f} target=${safe_target:.2f}"
                )

                req = MarketOrderRequest(
                    symbol=symbol,
                    qty=whole_qty,
                    side=order_side,
                    time_in_force=TimeInForce.DAY,
                    order_class=OrderClass.BRACKET,
                    stop_loss={"stop_price": safe_stop},
                    take_profit={"limit_price": safe_target},
                )
            else:
                # Simple market order — fractional OK here
                req = MarketOrderRequest(
                    symbol=symbol,
                    qty=round(qty, 2),
                    side=order_side,
                    time_in_force=TimeInForce.DAY,
                )

            order = self.trading.submit_order(req)
            logger.info(f"[ORDER PLACED]: {side.upper()} {whole_qty} shares {symbol}")
            return order

        except APIError as e:
            logger.error(f"Order failed for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected order error for {symbol}: {e}")
            return None

    def close_position(self, symbol: str):
        try:
            self.trading.close_position(symbol)
            logger.info(f"[CLOSED]: {symbol}")
        except Exception as e:
            logger.error(f"Failed to close {symbol}: {e}")

    def cancel_all_orders(self):
        self.trading.cancel_orders()

    # ── Market Data ─────────────────────────────────────────
    def get_bars(self, symbol: str, timeframe: str = "15Min",
                 limit: int = 250) -> pd.DataFrame:
        """
        Fetch OHLCV bars for a symbol.
        timeframe options: '1Min','5Min','15Min','30Min','1Hour','1Day'
        """
        try:
            # Calculate start date based on limit + timeframe
            if "Day" in timeframe:
                start = datetime.now(ET) - timedelta(days=limit + 10)
            elif "Hour" in timeframe:
                start = datetime.now(ET) - timedelta(hours=limit + 5)
            else:
                # Minutes: need more calendar days to get enough bars
                minutes = int(timeframe.replace("Min", ""))
                trading_minutes_per_day = 390
                days_needed = max(5, (limit * minutes) // trading_minutes_per_day + 5)
                start = datetime.now(ET) - timedelta(days=days_needed)

            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=_tf(timeframe),
                start=start,
                limit=limit,
                adjustment="raw",
            )
            bars_response = self.data.get_stock_bars(req)
            df = bars_response.df

            if df.empty:
                return pd.DataFrame()

            # alpaca-py returns multi-index (symbol, timestamp) — drop symbol level
            if isinstance(df.index, pd.MultiIndex):
                df = df.droplevel(0)

            df.index = pd.to_datetime(df.index)
            df = df[["open", "close", "high", "low", "volume"]].copy()
            return df.tail(limit)

        except Exception as e:
            logger.error(f"Error fetching bars for {symbol}: {e}")
            return pd.DataFrame()

    def get_latest_quote(self, symbol: str) -> Optional[dict]:
        try:
            req   = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = self.data.get_stock_latest_quote(req)[symbol]
            return {
                "symbol": symbol,
                "bid":    quote.bid_price,
                "ask":    quote.ask_price,
                "mid":    (quote.bid_price + quote.ask_price) / 2,
            }
        except Exception as e:
            logger.error(f"Quote error for {symbol}: {e}")
            return None

    def get_snapshot(self, symbols: list) -> dict:
        """Get latest snapshot for multiple symbols at once"""
        try:
            req       = StockSnapshotRequest(symbol_or_symbols=symbols)
            snapshots = self.data.get_stock_snapshot(req)
            result    = {}
            for sym, snap in snapshots.items():
                try:
                    latest_price = snap.latest_trade.price
                    prev_close   = snap.previous_daily_bar.close if snap.previous_daily_bar else latest_price
                    change_pct   = (latest_price - prev_close) / prev_close * 100 if prev_close else 0
                    daily_vol    = snap.daily_bar.volume if snap.daily_bar else 0
                    result[sym]  = {
                        "price":        latest_price,
                        "change_pct":   change_pct,
                        "daily_volume": daily_vol,
                    }
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.error(f"Snapshot error: {e}")
            return {}

    # ── Market Scanner ──────────────────────────────────────
    def get_top_movers(self, top_n: int = 20) -> list:
        """Scan a liquid universe and return top N movers by % change + volume"""
        universe = list(set([
            "AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","AMD","INTC","ORCL",
            "JPM","BAC","GS","WFC","MS","C","V","MA","PYPL","SQ",
            "JNJ","PFE","ABBV","MRK","UNH","CVS","AMGN",
            "XOM","CVX","COP","SLB","OXY",
            "WMT","TGT","COST","HD","LOW",
            "GLD","SLV","USO","UUP","FXE","SPY","QQQ","IWM","DIA",
            "NFLX","DIS","CMCSA","T","VZ","TMUS",
        ]))

        try:
            snapshots = self.get_snapshot(universe)
            ranked    = sorted(
                snapshots.items(),
                key=lambda x: (abs(x[1]["change_pct"]), x[1]["daily_volume"]),
                reverse=True,
            )
            return [sym for sym, _ in ranked[:top_n]]
        except Exception as e:
            logger.error(f"Scanner error: {e}")
            return config.WATCHLIST[:top_n]

    # ── Position Sizing ─────────────────────────────────────
    def calculate_position_size(self, price: float, stop_price: float) -> float:
        """
        Risk-based position sizing: risk 2% of portfolio per trade.
        Returns float — caller must convert to int for bracket orders.
        Minimum 1 whole share required for bracket orders.
        """
        portfolio      = self.get_portfolio_value()
        risk_amount    = portfolio * (config.RISK_PER_TRADE_PCT / 100)
        risk_per_share = abs(price - stop_price)
        if risk_per_share < 0.01:
            logger.warning(f"[SIZE] Stop too close to price (${risk_per_share:.4f}) — skipping")
            return 0
        qty     = risk_amount / risk_per_share
        max_qty = config.MAX_POSITION_SIZE / price
        final   = min(qty, max_qty)
        # Ensure at least 1 whole share (bracket orders require whole shares)
        if final < 1.0:
            logger.info(f"[SIZE] Qty {final:.2f} < 1 share — using 1 share minimum")
            return 1.0
        return round(final, 2)

    # ── Market Status ────────────────────────────────────────
    def is_market_open(self) -> bool:
        clock = self.trading.get_clock()
        return clock.is_open

    # ── News (via Alpaca News API) ───────────────────────────
    def get_news(self, symbols: list, limit: int = 10) -> list:
        """
        Fetch news from Alpaca's News API.
        No extra key needed — uses your trading API key.
        """
        try:
            import requests
            headers = {
                "APCA-API-KEY-ID":     config.ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
            }
            params = {
                "symbols": ",".join(symbols),
                "limit":   limit,
                "sort":    "desc",
            }
            resp = requests.get(
                "https://data.alpaca.markets/v1beta1/news",
                headers=headers,
                params=params,
                timeout=10,
            )
            if resp.status_code == 200:
                news_list = resp.json().get("news", [])
                return [
                    {
                        "headline":   n.get("headline", ""),
                        "summary":    n.get("summary", ""),
                        "source":     n.get("source", ""),
                        "symbols":    n.get("symbols", []),
                        "created_at": n.get("created_at", ""),
                        "url":        n.get("url", ""),
                    }
                    for n in news_list
                ]
        except Exception as e:
            logger.error(f"News fetch error: {e}")
        return []
