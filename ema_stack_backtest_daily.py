"""
ema_stack_backtest_daily.py
----------------------------
Longer-horizon backtest using Dhan DAILY historical candles (up to ~6 months)
for the EMA 8/24/72 stack crossover strategy.

Covers:
  - NIFTY 50 index (id 13)
  - BANK NIFTY index (id 25)
  - NIFTY 50 constituent stocks (all 48)

NOTE: Dhan's intraday API only gives ~5 days of 5-min data, so for a
statistically meaningful test we use DAILY candles here. Horizons are
measured in trading days (3/6/12/24 = ~2w/3w/6w/3m).

Options are NOT included here because this SDK build (2.0.2) has no
expired-options historical endpoint; the 5-min option test lives in
ema_stack_backtest_dhan_full.py.

USAGE:
    python ema_stack_backtest_daily.py

Output:
    dhan_daily_backtest.xlsx  (raw daily candles, one sheet per symbol)
    console report with win rates per symbol
"""

import datetime as dt
import time
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

from dhanhq import dhanhq

# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
import os

# Set these as environment variables before running:
#   Windows PowerShell:  $env:DHAN_CLIENT_ID="your_id"; $env:DHAN_ACCESS_TOKEN="your_token"
CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "YOUR_CLIENT_ID")
ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "YOUR_ACCESS_TOKEN")

CALL_DELAY = 1.0
HISTORY_FROM = "2023-01-01"   # ~3.5 years of daily candles

# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------
INDICES = {"NIFTY": "13", "BANKNIFTY": "25"}

NIFTY50 = {
    "ADANIPORTS": "15083", "APOLLOHOSP": "157", "ASIANPAINT": "236",
    "AXISBANK": "5900", "BAJAJ-AUTO": "16669", "BAJAJFINSV": "16675",
    "BAJFINANCE": "317", "BHARTIARTL": "10604", "BPCL": "526",
    "BRITANNIA": "547", "CIPLA": "694", "COALINDIA": "20374",
    "DIVISLAB": "10940", "DRREDDY": "881", "EICHERMOT": "910",
    "GRASIM": "1232", "HCLTECH": "7229", "HDFCBANK": "1333",
    "HDFCLIFE": "467", "HEROMOTOCO": "1348", "HINDUNILVR": "1394",
    "ICICIBANK": "4963", "INDUSINDBK": "5258", "INFY": "1594",
    "ITC": "1660", "JSWSTEEL": "11723", "KOTAKBANK": "1922",
    "LT": "11483", "M&M": "2031", "MARUTI": "10999",
    "NESTLEIND": "17963", "NTPC": "11630", "ONGC": "2475",
    "PIDILITIND": "2664", "POWERGRID": "14977", "RELIANCE": "2885",
    "SBILIFE": "21808", "SBIN": "3045", "SUNPHARMA": "3351",
    "TATACONSUM": "3432", "TATASTEEL": "3499", "TCS": "11536",
    "TECHM": "13538", "TITAN": "3506", "ULTRACEMCO": "11532",
    "UPL": "11287", "VEDL": "3063", "WIPRO": "3787",
}

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
EMA_FAST, EMA_MID, EMA_SLOW = 8, 24, 72
VOLUME_LOOKBACK = 20
VOLUME_CONFIRM_RATIO = 1.3
HORIZONS = [3, 6, 12, 24]   # trading DAYS ahead


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _client():
    return dhanhq(CLIENT_ID, ACCESS_TOKEN)


def _call_with_retry(fn, attempts=4, base_delay=2.0):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if "DH-904" in str(e) and i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
                continue
            raise


def fetch_daily_equity(symbol, sid):
    d = _client()
    time.sleep(CALL_DELAY)
    resp = _call_with_retry(lambda: d.historical_daily_data(
        sid, "NSE_EQ", "EQUITY", HISTORY_FROM, dt.date.today().strftime("%Y-%m-%d")))
    return _to_df(symbol, resp)


def fetch_daily_index(symbol, sid):
    d = _client()
    time.sleep(CALL_DELAY)
    resp = _call_with_retry(lambda: d.historical_daily_data(
        sid, "IDX_I", "INDEX", HISTORY_FROM, dt.date.today().strftime("%Y-%m-%d")))
    return _to_df(symbol, resp)


def _to_df(symbol, resp):
    if resp.get("status") != "success":
        raise RuntimeError(f"{symbol}: {resp.get('remarks')}")
    data = resp["data"]
    n = len(data.get("timestamp", []))
    if n == 0:
        raise RuntimeError(f"{symbol}: empty")
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(pd.to_numeric(data["timestamp"]), unit="s"),
        "open": pd.to_numeric(data["open"]),
        "high": pd.to_numeric(data["high"]),
        "low": pd.to_numeric(data["low"]),
        "close": pd.to_numeric(data["close"]),
        "volume": pd.to_numeric(data["volume"]),
    }).sort_values("timestamp").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def compute_signals(df):
    df = df.copy()
    df["ema8"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema24"] = df["close"].ewm(span=EMA_MID, adjust=False).mean()
    df["ema72"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    df["bull_stack"] = (df["ema8"] > df["ema24"]) & (df["ema24"] > df["ema72"])
    df["bear_stack"] = (df["ema8"] < df["ema24"]) & (df["ema24"] < df["ema72"])
    df["fresh_bull"] = df["bull_stack"] & ~df["bull_stack"].shift(1).fillna(False)
    df["fresh_bear"] = df["bear_stack"] & ~df["bear_stack"].shift(1).fillna(False)
    df["avg_vol"] = df["volume"].rolling(VOLUME_LOOKBACK).mean()
    df["vol_ratio"] = df["volume"] / df["avg_vol"]
    df["vol_confirmed"] = df["vol_ratio"] >= VOLUME_CONFIRM_RATIO
    return df


def forward_returns(df, signal_col, direction, horizons):
    rows = []
    for i in df.index[df[signal_col]]:
        entry = df.loc[i, "close"]
        row = {"entry_ts": df.loc[i, "timestamp"], "entry_price": entry,
               "vol_ratio": df.loc[i, "vol_ratio"]}
        for h in horizons:
            j = i + h
            if j >= len(df):
                row[f"ret_{h}"] = float("nan")
                continue
            row[f"ret_{h}"] = ((df.loc[j, "close"] - entry) / entry * 100) * direction
        max_h = max(horizons)
        window = df.loc[i:min(i + max_h, len(df) - 1)]
        row["max_adverse_pct"] = ((window["low"].min() - entry) / entry * 100) if direction == 1 \
            else ((entry - window["high"].max()) / entry * 100)
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(trades, horizons, label):
    print(f"\n{'='*64}\n  {label}  -  {len(trades)} signals\n{'='*64}")
    if trades.empty:
        print("  No signals fired in this dataset.")
        return
    for h in horizons:
        v = trades[f"ret_{h}"].dropna()
        if v.empty:
            continue
        wr = (v > 0).mean() * 100
        ar = v.mean()
        aw = v[v > 0].mean() if (v > 0).any() else 0
        al = v[v <= 0].mean() if (v <= 0).any() else 0
        print(f"  +{h}d: WR {wr:5.1f}% | avg {ar:+.3f}% | win {aw:+.3f}% | "
              f"loss {al:+.3f}% (n={len(v)})")
    print(f"  Avg max adverse excursion: {trades['max_adverse_pct'].mean():+.3f}%")


def run_one(symbol, df, use_volume_filter=True):
    df = compute_signals(df)
    if use_volume_filter:
        bull = df["fresh_bull"] & df["vol_confirmed"]
        bear = df["fresh_bear"] & df["vol_confirmed"]
        tag = "vol confirmed"
    else:
        # indices carry no real volume, so run the raw stack crossover
        bull = df["fresh_bull"]
        bear = df["fresh_bear"]
        tag = "no vol filter"
    bt = forward_returns(df.assign(s=bull), "s", +1, HORIZONS)
    br = forward_returns(df.assign(s=bear), "s", -1, HORIZONS)
    summarize(bt, HORIZONS, f"{symbol} - BULL ({tag})")
    summarize(br, HORIZONS, f"{symbol} - BEAR ({tag})")
    return bt, br


def _stat_row(symbol, side, trades, h=6):
    col = f"ret_{h}"
    v = trades[col].dropna() if not trades.empty else pd.Series(dtype=float)
    if v.empty:
        return None
    return {
        "symbol": symbol, "side": side, "signals": len(v),
        "win_rate": round((v > 0).mean() * 100, 1),
        "avg_ret": round(v.mean(), 3),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    sheets = {}
    ranking = []

    # indices
    for sym, sid in INDICES.items():
        try:
            print(f"[+] {sym} daily ...")
            df = fetch_daily_index(sym, sid)
            sheets[sym] = df
            df.to_csv(f"{sym.lower()}_daily.csv", index=False)
            bt, br = run_one(sym, df, use_volume_filter=False)
            for r in (_stat_row(sym, "BULL", bt), _stat_row(sym, "BEAR", br)):
                if r:
                    ranking.append(r)
        except Exception as e:
            print(f"  {sym} failed: {e}")

    # nifty50 stocks
    print(f"\n[+] NIFTY 50 stocks daily ({len(NIFTY50)}) ...")
    for sym, sid in NIFTY50.items():
        try:
            df = fetch_daily_equity(sym, sid)
            sheets[sym] = df
            df.to_csv(f"nifty50_{sym.lower()}_daily.csv", index=False)
            bt, br = run_one(sym, df)
            for r in (_stat_row(sym, "BULL", bt), _stat_row(sym, "BEAR", br)):
                if r:
                    ranking.append(r)
        except Exception as e:
            print(f"  {sym} skipped: {e}")

    excel = "dhan_daily_backtest.xlsx"
    with pd.ExcelWriter(excel, engine="openpyxl") as w:
        for sym, df in sheets.items():
            df.to_excel(w, sheet_name=sym[:31], index=False)
        # ranking sheet
        rank_df = pd.DataFrame(ranking).sort_values(
            ["win_rate", "avg_ret"], ascending=False)
        rank_df.to_excel(w, sheet_name="RANKING", index=False)
    print(f"\n[+] Excel -> {excel}  ({len(sheets)} sheets + RANKING)")

    # ---- console ranking table (best +6d win rate, min 5 signals) ----
    rank_df = pd.DataFrame(ranking)
    if not rank_df.empty:
        reliable = rank_df[rank_df["signals"] >= 5].sort_values(
            ["win_rate", "avg_ret"], ascending=False)
        print(f"\n{'='*64}")
        print("  TOP BY WIN RATE  (+6 trading days, min 5 signals)")
        print(f"{'='*64}")
        print(f"  {'SYMBOL':<12} {'SIDE':<5} {'SIGNALS':>7} {'WIN%':>7} {'AVG%':>8}")
        for _, r in reliable.head(20).iterrows():
            print(f"  {r['symbol']:<12} {r['side']:<5} {int(r['signals']):>7} "
                  f"{r['win_rate']:>6.1f}% {r['avg_ret']:>+7.3f}%")


if __name__ == "__main__":
    main()
