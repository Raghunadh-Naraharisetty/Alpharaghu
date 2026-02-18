# 🚀 ALPHARAGHU — Algorithmic Trading Bot

> **Live signals. Real-time news. 3 battle-tested strategies. Telegram alerts.**
> Built on Alpaca Paper Trading API.

---

## 📁 Project Structure

```
Alpharaghu/
├── main.py                          ← 🔴 Run this!
├── config.py                        ← All settings
├── .env                             ← Your API keys (create from .env.example)
├── requirements.txt
│
├── broker/
│   └── alpaca_client.py             ← Alpaca API + market scanner
│
├── strategies/
│   ├── __init__.py                  ← Strategy combiner (consensus logic)
│   ├── strategy1_momentum.py        ← 📈 RSI + MACD + EMA200
│   ├── strategy2_mean_reversion.py  ← 🔄 Bollinger Bands + Stochastic
│   └── strategy3_news_sentiment.py  ← 📰 News + Earnings catalyst
│
├── notifications/
│   └── telegram_bot.py              ← Telegram signal alerts
│
├── data/
│   └── news_fetcher.py              ← Alpaca News + NewsAPI + yfinance
│
└── logs/
    └── alpharaghu.log
```

---

## ⚡ Quick Start (5 Minutes)

### 1. Clone & Install
```bash
git clone https://github.com/YOUR_USERNAME/Alpharaghu.git
cd Alpharaghu
pip install -r requirements.txt
```

### 2. Configure API Keys
```bash
cp .env.example .env
nano .env   # Fill in your credentials
```

### 3. Get Your Keys

| Key | Where to Get |
|-----|-------------|
| Alpaca Paper API | [app.alpaca.markets](https://app.alpaca.markets) → Paper Trading → API Keys |
| Telegram Bot Token | Message [@BotFather](https://t.me/botfather) → `/newbot` |
| Telegram Chat ID | Add [@userinfobot](https://t.me/userinfobot) to your group → it shows the chat ID |
| NewsAPI (optional) | [newsapi.org](https://newsapi.org) → free tier (100 req/day) |

### 4. Run the Bot
```bash
python main.py
```

---

## 📊 Three Strategies Explained

### Strategy 1: 📈 Momentum (RSI + MACD + EMA200)
Best for: **Trending markets, breakouts**

**BUY when:**
- Price is above EMA200 (in uptrend)
- RSI crosses above 50 from below
- MACD line crosses above signal line
- Volume is 1.5× average (confirms real move)

**SELL when:**
- RSI drops below 50
- MACD bearish crossover
- RSI becomes overbought (>75)

---

### Strategy 2: 🔄 Mean Reversion (Bollinger Bands + Stochastic)
Best for: **Sideways markets, oversold bounces**

**BUY when:**
- Price touches/breaks below Lower Bollinger Band
- RSI < 35 (oversold)
- Stochastic %K < 20 and crosses above %D
- Exit target: Middle Band (the mean)

**SELL when:**
- Price reaches Upper Band or Middle Band
- RSI > 65 (overbought)
- Stochastic bearish crossover

---

### Strategy 3: 📰 News Sentiment + Earnings
Best for: **Earnings season, major news events**

**BUY when:**
- Positive news score > 0.3 threshold
- Multiple bullish articles (beats, upgrades, approvals)
- Earnings growth > 10% YoY
- Price hasn't already run > 3% (not too late)

**SELL when:**
- Negative sentiment score
- Earnings miss detected
- Price already up > 3% on news (fade the news)

---

## 🤝 Consensus Logic

A trade only executes if **at least 2 of 3 strategies agree** (or 1 very strong signal):

```
Strategy 1  🟢 BUY  (strength: 80%)  ←─┐
Strategy 2  🟢 BUY  (strength: 65%)  ←─┤  2/3 agree → ✅ EXECUTE BUY
Strategy 3  ⚪ HOLD (strength: 20%)     │
```

This prevents false signals and noisy trades.

---

## 📱 Telegram Signals Format

```
╔══════════════════════════╗
  🚀 BUY SIGNAL  🟢
╚══════════════════════════╝

📊 AAPL
🕐 2024-01-15 10:32 ET
🎯 Confidence: 78%  |  2/3 strategies agree

📌 Levels
  Entry:        $185.20
  Stop Loss:    $181.50
  Take Profit:  $192.60

Strategy Breakdown:
  🟢 Momentum: BUY (80%) — price above EMA200 | RSI crossed 50 | MACD crossover
  🟢 Mean Reversion: BUY (65%) — price at Lower BB | RSI oversold (32)
  ⚪ News Sentiment: HOLD (20%) — Neutral news | score:0.05

#alpharaghu #AAPL #buy
```

---

## 🌍 Symbol Coverage

### US Stocks (via Alpaca)
Any US-listed stock. Default watchlist includes AAPL, MSFT, NVDA, TSLA, etc.

### Commodities (as ETFs on Alpaca)
| Commodity | ETF Symbol | What it Tracks |
|-----------|-----------|---------------|
| Gold      | GLD       | Gold price    |
| Silver    | SLV       | Silver price  |
| Oil       | USO       | Crude oil     |
| Natural Gas | UNG     | Natural gas   |

### Forex (as ETFs on Alpaca)
| Currency  | ETF Symbol | What it Tracks |
|-----------|-----------|---------------|
| US Dollar | UUP       | USD index     |
| Euro      | FXE       | EUR/USD       |
| Yen       | FXY       | USD/JPY       |

> **Note:** Alpaca does not offer direct forex or futures trading.
> ETFs are the safest, regulated way to get exposure using the same strategies.

---

## ⚙️ Configuration Reference

```env
# Risk Management
MAX_POSITION_SIZE=1000      # Max $ per trade
RISK_PER_TRADE_PCT=2        # Risk 2% of portfolio per trade
STOP_LOSS_PCT=2             # 2% stop loss below entry
TAKE_PROFIT_PCT=4           # 4% take profit (2:1 reward:risk ratio)
MAX_OPEN_POSITIONS=5        # Never hold more than 5 stocks at once

# Scanning
SCAN_INTERVAL_MINUTES=15    # Scan every 15 min during market hours
USE_DYNAMIC_SCANNER=true    # Add top movers to watchlist dynamically
```

---

## 🛡️ Risk Management Built-In

- ✅ 2:1 reward-to-risk ratio enforced
- ✅ Automatic stop loss on every trade (bracket orders)
- ✅ Max position size limits
- ✅ Max open positions cap (default: 5)
- ✅ No duplicate signals within 30 minutes
- ✅ No trades outside market hours
- ✅ Volume confirmation on every signal
- ✅ Consensus required (2/3 strategies must agree)

---

## 📈 Upgrading to Live Trading

When you're ready to go live:
1. Change `.env`:
   ```
   ALPACA_BASE_URL=https://api.alpaca.markets
   ```
2. Replace your paper API keys with live keys from [app.alpaca.markets](https://app.alpaca.markets)
3. Start small (reduce `MAX_POSITION_SIZE` to $100–$500)

---

## 📞 Support

Built by **ALPHARAGHU** team. For issues, check `logs/alpharaghu.log`.
