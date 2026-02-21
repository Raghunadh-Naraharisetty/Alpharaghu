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
          2. stop_price must be <= base_price - 0.01  (round DOWN using floor)
          3. take_profit must be >= base_price + 0.01 (round UP using ceil)
          4. Use GTC (Good Till Cancelled) so stops persist overnight
          5. Recalculate stop/target from LIVE price at order time, not signal time
        """
        import math
        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

            # ── Whole shares for bracket orders ───────────────
            whole_qty = max(1, int(qty))   # floor to whole number, minimum 1

            if stop_loss and take_profit:
                # ── FIX: Fetch live mid-price at order submission time ──
                # stop/target were calculated at signal time but price may have
                # moved by the time we submit — recalculate from live price
                live_quote = self.get_latest_quote(symbol)
                if live_quote and live_quote.get("mid"):
                    live_price = live_quote["mid"]
                    # Recalculate stop/target as pct offsets from live price
                    stop_pct   = abs(stop_loss - 0) / stop_loss if stop_loss else config.STOP_LOSS_PCT / 100
                    # Derive pct from original signal prices
                    orig_entry = (stop_loss / (1 - config.STOP_LOSS_PCT / 100))
                    stop_pct   = config.STOP_LOSS_PCT   / 100
                    target_pct = config.TAKE_PROFIT_PCT / 100
                    recalc_stop   = live_price * (1 - stop_pct)
                    recalc_target = live_price * (1 + target_pct)
                    logger.info(
                        f"[PRICE REFRESH] {symbol}: signal=${orig_entry:.2f} "
                        f"live=${live_price:.2f} → recalc stop/target"
                    )
                    stop_loss   = recalc_stop
                    take_profit = recalc_target

                # ── Safe stop price (always round DOWN) ────────
                # Guarantees stop is always at least $0.01 below base price
                safe_stop   = math.floor(stop_loss   * 100) / 100

                # ── Safe target price (always round UP) ─────────
                # Guarantees target is always at least $0.01 above base price
                safe_target = math.ceil(take_profit  * 100) / 100

                logger.info(
                    f"[ORDER PREP] {symbol}: qty={whole_qty} "
                    f"stop=${safe_stop:.2f} target=${safe_target:.2f}"
                )

                # ── GTC: stops persist overnight until triggered ─
                # DAY orders expire at 4 PM — positions unprotected overnight
                # GTC stays active until price hits stop OR target
                req = MarketOrderRequest(
                    symbol=symbol,
                    qty=whole_qty,
                    side=order_side,
                    time_in_force=TimeInForce.GTC,
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

        # Max price filter — stocks above $300 result in < 3 shares per position
        # which makes position sizing impractical for our $2k max position size
        MAX_STOCK_PRICE = 300.0

        try:
            snapshots = self.get_snapshot(universe)
            # Filter out stocks too expensive for practical position sizing
            affordable = {
                sym: data for sym, data in snapshots.items()
                if data.get("price", 0) <= MAX_STOCK_PRICE
            }
            excluded = [s for s in snapshots if s not in affordable]
            if excluded:
                logger.debug(f"[SCANNER] Excluded high-price stocks: {excluded}")
            ranked    = sorted(
                affordable.items(),
                key=lambda x: (abs(x[1]["change_pct"]), x[1]["daily_volume"]),
                reverse=True,
            )
            return [sym for sym, _ in ranked[:top_n]]
        except Exception as e:
            logger.error(f"Scanner error: {e}")
            return config.WATCHLIST[:top_n]

    # ── Position Sizing ─────────────────────────────────────
    def get_atr(self, symbol: str, period: int = 14) -> float:
        """
        Calculate Average True Range (ATR) for a symbol.
        ATR measures real volatility — how much a stock moves per bar on average.
        Used by ATR position sizing to adapt stop distance to actual market conditions.
        """
        try:
            df = self.get_bars(symbol, timeframe="1Day", limit=period + 5)
            if df.empty or len(df) < period:
                return 0.0
            high  = df["high"]
            low   = df["low"]
            close = df["close"]
            # True Range = max of: (H-L), |H-prev_C|, |L-prev_C|
            prev_close = close.shift(1)
            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low  - prev_close).abs(),
            ], axis=1).max(axis=1)
            atr = tr.rolling(period).mean().iloc[-1]
            return float(atr) if not pd.isna(atr) else 0.0
        except Exception as e:
            logger.error(f"ATR calculation error for {symbol}: {e}")
            return 0.0

    def calculate_position_size(self, price: float, stop_price: float,
                                 symbol: str = None) -> float:
        """
        Risk-based position sizing — two modes controlled by config.POSITION_SIZE_METHOD:

        "fixed" (original):
            Stop = fixed % below entry (STOP_LOSS_PCT)
            Simple, predictable, same % stop for every stock

        "atr" (new — adapted from friend's bot):
            Stop = entry - (ATR × ATR_STOP_MULTIPLIER)
            Target = entry + (ATR × ATR_TARGET_MULTIPLIER)
            Adapts to real volatility — high-vol stocks get smaller
            positions, low-vol stocks get larger, both risk the same $

        Both methods:
            - Risk exactly RISK_PER_TRADE_PCT % of portfolio per trade
            - Cap at MAX_POSITION_SIZE dollars
            - Minimum 1 whole share (Alpaca bracket order requirement)
        """
        portfolio   = self.get_portfolio_value()
        risk_amount = portfolio * (config.RISK_PER_TRADE_PCT / 100)

        method = getattr(config, "POSITION_SIZE_METHOD", "fixed").lower()

        if method == "atr" and symbol:
            # ── ATR Method ─────────────────────────────────────
            atr = self.get_atr(symbol)
            if atr > 0:
                stop_multiplier   = getattr(config, "ATR_STOP_MULTIPLIER",   2.0)
                target_multiplier = getattr(config, "ATR_TARGET_MULTIPLIER", 4.0)
                atr_stop_dist     = atr * stop_multiplier
                atr_stop_price    = price - atr_stop_dist
                atr_target_price  = price + (atr * target_multiplier)
                risk_per_share    = atr_stop_dist

                atr_pct = (atr / price) * 100
                logger.info(
                    f"[SIZE-ATR] {symbol}: ATR=${atr:.2f} ({atr_pct:.1f}%) | "
                    f"stop=${atr_stop_price:.2f} target=${atr_target_price:.2f}"
                )
                # Return as tuple so caller can use ATR-based stop/target
                # if caller only wants qty, the atr_stop/target are logged
                qty = risk_amount / risk_per_share
                max_qty = config.MAX_POSITION_SIZE / price
                final = min(qty, max_qty)
                if final < 1.0:
                    logger.info(f"[SIZE-ATR] Qty {final:.2f} < 1 share — using 1 minimum")
                    return 1.0
                logger.info(
                    f"[SIZE-ATR] {symbol}: qty={final:.1f} | "
                    f"risk=${risk_amount:.0f} / ${risk_per_share:.2f}/share"
                )
                return round(final, 2)
            else:
                logger.warning(f"[SIZE-ATR] {symbol}: ATR=0, falling back to fixed sizing")
                # Fall through to fixed method below

        # ── Fixed Method (default / fallback) ──────────────────
        risk_per_share = abs(price - stop_price)
        if risk_per_share < 0.01:
            logger.warning(f"[SIZE] Stop too close to price (${risk_per_share:.4f}) — skipping")
            return 0
        qty     = risk_amount / risk_per_share
        max_qty = config.MAX_POSITION_SIZE / price
        final   = min(qty, max_qty)
        if final < 1.0:
            logger.info(f"[SIZE] Qty {final:.2f} < 1 share — using 1 share minimum")
            return 1.0
        logger.info(
            f"[SIZE-FIXED] qty={final:.1f} | "
            f"risk=${risk_amount:.0f} / ${risk_per_share:.2f}/share"
        )
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
