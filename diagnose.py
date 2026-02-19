"""
ALPHARAGHU - Diagnostic Tool
Run: python diagnose.py
Shows exactly why strategies are returning 0% confidence
"""
import sys, os, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ["PYTHONUTF8"] = "1"

def load(name, *parts):
    path = os.path.join(ROOT, *parts)
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

config     = load("config",        "config.py")
alpaca_mod = load("alpaca_client", "broker", "alpaca_client.py")
s1_mod     = load("strategy1",     "strategies", "strategy1_momentum.py")
s2_mod     = load("strategy2",     "strategies", "strategy2_mean_reversion.py")

client = alpaca_mod.AlpacaClient()

TEST_SYMBOLS = ["AAPL", "NVDA", "SPY", "TSLA", "MSFT"]

print("\n" + "="*60)
print("  ALPHARAGHU DIAGNOSTIC REPORT")
print("="*60)

# ── 1. Account & Positions ───────────────────────────────────
print("\n[1] ACCOUNT & ALL POSITIONS (including manual)")
acct = client.get_account()
print(f"  Portfolio: ${float(acct.portfolio_value):,.2f}")
print(f"  Cash:      ${float(acct.cash):,.2f}")

positions = client.get_positions()
if positions:
    for p in positions:
        pl  = float(p.unrealized_pl)
        pct = float(p.unrealized_plpc) * 100
        print(f"  POSITION: {p.symbol} | qty:{p.qty} | "
              f"entry:${float(p.avg_entry_price):.2f} | "
              f"current:${float(p.current_price):.2f} | "
              f"P&L:${pl:+.2f} ({pct:+.1f}%)")
else:
    print("  No positions found via API")

# ── 2. Data Check ────────────────────────────────────────────
print("\n[2] DATA AVAILABILITY CHECK")
for sym in TEST_SYMBOLS:
    df15  = client.get_bars(sym, "15Min", limit=250)
    df1d  = client.get_bars(sym, "1Day",  limit=252)
    print(f"  {sym}: 15min={len(df15)} bars | daily={len(df1d)} bars | "
          f"latest=${df15['close'].iloc[-1]:.2f}" if not df15.empty else f"  {sym}: NO DATA")

# ── 3. Strategy Deep Dive ─────────────────────────────────────
print("\n[3] STRATEGY INDICATOR VALUES (why HOLD?)")
strat1 = s1_mod.MomentumStrategy()
strat2 = s2_mod.MeanReversionStrategy()

for sym in ["AAPL", "NVDA", "SPY"]:
    df = client.get_bars(sym, "15Min", limit=250)
    if df.empty or len(df) < 50:
        print(f"  {sym}: SKIPPED - only {len(df)} bars")
        continue

    r1 = strat1.generate_signal(df)
    r2 = strat2.generate_signal(df)

    print(f"\n  {sym}:")
    print(f"    Bars available: {len(df)}")

    ind1 = r1.get("indicators", {})
    if ind1:
        print(f"    Momentum indicators:")
        print(f"      Price:  ${ind1.get('price', 0):.2f} | "
              f"EMA200: ${ind1.get('ema200', 0):.2f} | "
              f"EMA50:  ${ind1.get('ema50', 0):.2f}")
        print(f"      RSI:    {ind1.get('rsi', 0):.1f} | "
              f"MACD:   {ind1.get('macd', 0):.4f} | "
              f"Signal: {ind1.get('signal', 0):.4f}")
        print(f"      Vol ratio: {ind1.get('vol_ratio', 0):.2f}x")
        above_ema = ind1.get('price',0) > ind1.get('ema200',0)
        print(f"      Above EMA200: {above_ema}  <-- key filter!")

    ind2 = r2.get("indicators", {})
    if ind2:
        print(f"    Mean Reversion indicators:")
        print(f"      BB Lower: ${ind2.get('bb_lower',0):.2f} | "
              f"BB Mid: ${ind2.get('bb_mid',0):.2f} | "
              f"BB Upper: ${ind2.get('bb_upper',0):.2f}")
        print(f"      RSI: {ind2.get('rsi',0):.1f} | "
              f"Stoch K: {ind2.get('stoch_k',0):.1f} | "
              f"Stoch D: {ind2.get('stoch_d',0):.1f}")

    print(f"    Strategy 1 (Momentum):      {r1['signal']} | {r1['reason']}")
    print(f"    Strategy 2 (Mean Reversion): {r2['signal']} | {r2['reason']}")

# ── 4. Threshold Analysis ─────────────────────────────────────
print("\n[4] CURRENT THRESHOLDS (may be too strict)")
print(f"  Momentum  BUY threshold:       60% (both RSI+MACD must cross simultaneously)")
print(f"  MeanRev   BUY threshold:       55% (price at BB lower + RSI oversold)")
print(f"  Consensus required:            2/3 strategies agree")
print(f"  --> FIX: Lower to 45% and allow 1 strong signal")

print("\n" + "="*60)
print("  END DIAGNOSTIC")
print("="*60 + "\n")
