"""
ema_stack_backtest_dhan_full.py
-------------------------------
Fetches 5-minute OHLCV candles DIRECTLY from the Dhan API and runs the
8/24/72 EMA stack crossover backtest for:

  A) NIFTY 50 constituent stocks (all 50, top liquid names)
  B) BANK NIFTY index (spot)
  C) BANK NIFTY current-month ATM option (both CE and PE)

Win rate / avg return are reported per instrument, and everything is
exported to Excel (one sheet per symbol).

USAGE:
    python ema_stack_backtest_dhan_full.py

Requires: dhanhq, pandas, openpyxl
"""

import datetime as dt
import time
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

from dhanhq import dhanhq

# ---------------------------------------------------------------------------
# Dhan credentials
# ---------------------------------------------------------------------------
import os

# Set these as environment variables before running:
#   Windows PowerShell:  $env:DHAN_CLIENT_ID="your_id"; $env:DHAN_ACCESS_TOKEN="your_token"
CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "YOUR_CLIENT_ID")
ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "YOUR_ACCESS_TOKEN")

# Dhan caps intraday history at ~5 trading days
LOOKBACK_DAYS = 5
CALL_DELAY = 1.0  # seconds between API calls to respect rate limits

# ---------------------------------------------------------------------------
# Instrument universe
# ---------------------------------------------------------------------------
# NIFTY 50 constituents (trading symbol -> Dhan security id)
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

# BANK NIFTY index (spot)
BANKNIFTY_ID = "25"

# ---------------------------------------------------------------------------
# Backtest config
# ---------------------------------------------------------------------------
EMA_FAST, EMA_MID, EMA_SLOW = 8, 24, 72
VOLUME_LOOKBACK = 20
VOLUME_CONFIRM_RATIO = 1.3
HORIZONS = [3, 6, 12, 24]


# ---------------------------------------------------------------------------
# Dhan helpers
# ---------------------------------------------------------------------------
def _client():
    return dhanhq(CLIENT_ID, ACCESS_TOKEN)


def fetch_5min_equity(symbol, security_id):
    to_date = dt.date.today()
    from_date = to_date - dt.timedelta(days=LOOKBACK_DAYS)
    d = _client()
    time.sleep(CALL_DELAY)
    resp = _call_with_retry(lambda: d.intraday_minute_data(
        security_id, "NSE_EQ", "EQUITY",
        from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d"), interval=5,
    ))
    return _to_df(symbol, resp)


def fetch_5min_index(symbol, security_id):
    to_date = dt.date.today()
    from_date = to_date - dt.timedelta(days=LOOKBACK_DAYS)
    d = _client()
    time.sleep(CALL_DELAY)
    resp = _call_with_retry(lambda: d.intraday_minute_data(
        security_id, "IDX_I", "INDEX",
        from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d"), interval=5,
    ))
    return _to_df(symbol, resp)


def fetch_5min_option(symbol, security_id):
    to_date = dt.date.today()
    from_date = to_date - dt.timedelta(days=LOOKBACK_DAYS)
    d = _client()
    time.sleep(CALL_DELAY)
    resp = _call_with_retry(lambda: d.intraday_minute_data(
        security_id, "NSE_FNO", "OPTIDX",
        from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d"), interval=5,
    ))
    return _to_df(symbol, resp)


def _call_with_retry(fn, attempts=4, base_delay=2.0):
    """Retry on Dhan rate-limit (DH-904) errors with exponential backoff."""
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            if "DH-904" in msg and i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
                continue
            raise


def _to_df(symbol, resp):
    if resp.get("status") != "success":
        raise RuntimeError(f"{symbol}: Dhan error -> {resp.get('remarks')}")
    data = resp["data"]
    n = len(data.get("timestamp", []))
    if n == 0:
        raise RuntimeError(f"{symbol}: no candles returned (empty)")
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(pd.to_numeric(data["timestamp"]), unit="s"),
        "open": pd.to_numeric(data["open"]),
        "high": pd.to_numeric(data["high"]),
        "low": pd.to_numeric(data["low"]),
        "close": pd.to_numeric(data["close"]),
        "volume": pd.to_numeric(data["volume"]),
    }).sort_values("timestamp").reset_index(drop=True)
    return df


def get_banknifty_atm_option_ids(expiry):
    """Return (ce_security_id, pe_security_id) for the ATM strike of BANKNIFTY."""
    d = _client()
    time.sleep(CALL_DELAY)
    oc = _call_with_retry(lambda: d.option_chain(
        under_security_id=int(BANKNIFTY_ID),
        under_exchange_segment="IDX_I", expiry=expiry))

    def find(dct, key):
        if isinstance(dct, dict):
            if key in dct:
                return dct[key]
            for v in dct.values():
                r = find(v, key)
                if r is not None:
                    return r
        return None

    ocd = find(oc, "oc")
    spot = find(oc, "last_price")
    if not ocd or spot is None:
        raise RuntimeError(f"option_chain failed -> {str(oc)[:120]}")
    atm = min(ocd.keys(), key=lambda k: abs(float(k) - spot))
    ce_id = str(ocd[atm]["ce"]["security_id"])
    pe_id = str(ocd[atm]["pe"]["security_id"])
    return ce_id, pe_id, float(atm), float(spot)


def get_banknifty_monthly_expiry():
    d = _client()
    time.sleep(CALL_DELAY)
    ex = _call_with_retry(lambda: d.expiry_list(
        under_security_id=int(BANKNIFTY_ID),
        under_exchange_segment="IDX_I"))
    dates = ex.get("data", {}).get("data", [])
    if not dates:
        raise RuntimeError(f"expiry_list failed -> {str(ex)[:120]}")
    # current/next month expiry = first date on/after today
    today = dt.date.today()
    future = [dt.date.fromisoformat(x) for x in dates if dt.date.fromisoformat(x) >= today]
    return (future[0] if future else dt.date.fromisoformat(dates[0])).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Backtest logic
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
        print(f"  +{h}c ({h*5}min): WR {wr:5.1f}% | avg {ar:+.3f}% | "
              f"win {aw:+.3f}% | loss {al:+.3f}% (n={len(v)})")
    print(f"  Avg max adverse excursion: {trades['max_adverse_pct'].mean():+.3f}%")


def run_one(symbol, df):
    df = compute_signals(df)
    bull = df["fresh_bull"] & df["vol_confirmed"]
    bear = df["fresh_bear"] & df["vol_confirmed"]
    summarize(forward_returns(df.assign(s=bull), "s", +1, HORIZONS), HORIZONS,
              f"{symbol} - BULL (vol confirmed)")
    summarize(forward_returns(df.assign(s=bear), "s", -1, HORIZONS), HORIZONS,
              f"{symbol} - BEAR (vol confirmed)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    sheets = {}
    results = []

    # ---- BANK NIFTY spot ----
    try:
        print("[+] BANKNIFTY index ...")
        df = fetch_5min_index("BANKNIFTY", BANKNIFTY_ID)
        sheets["BANKNIFTY"] = df
        df.to_csv("banknifty_5min.csv", index=False)
        run_one("BANKNIFTY", df)
    except Exception as e:
        print(f"  BANKNIFTY failed: {e}")

    # ---- BANK NIFTY ATM monthly option ----
    try:
        expiry = get_banknifty_monthly_expiry()
        ce_id, pe_id, atm, spot = get_banknifty_atm_option_ids(expiry)
        print(f"[+] BANKNIFTY ATM option: strike {atm:.0f} (spot {spot:.0f}), "
              f"expiry {expiry}, CE={ce_id} PE={pe_id}")
        for name, sid in [("BANKNIFTY_CE", ce_id), ("BANKNIFTY_PE", pe_id)]:
            try:
                df = fetch_5min_option(name, sid)
                sheets[name] = df
                df.to_csv(f"{name.lower()}_5min.csv", index=False)
                run_one(name, df)
            except Exception as e:
                print(f"  {name} failed: {e}")
    except Exception as e:
        print(f"  BANKNIFTY option failed: {e}")

    # ---- NIFTY 50 constituents ----
    print(f"\n[+] NIFTY 50 constituents ({len(NIFTY50)} stocks) ...")
    for sym, sid in NIFTY50.items():
        try:
            df = fetch_5min_equity(sym, sid)
            sheets[sym] = df
            df.to_csv(f"nifty50_{sym.lower()}_5min.csv", index=False)
            run_one(sym, df)
            results.append((sym, len(df)))
        except Exception as e:
            print(f"  {sym} skipped: {e}")

    # ---- Excel export ----
    excel = "dhan_backtest_data.xlsx"
    with pd.ExcelWriter(excel, engine="openpyxl") as w:
        for sym, df in sheets.items():
            df.to_excel(w, sheet_name=sym[:31], index=False)
    print(f"\n[+] Excel exported -> {excel}  ({len(sheets)} sheets)")
    print(f"[+] Nifty50 stocks fetched: {len(results)}/{len(NIFTY50)}")


if __name__ == "__main__":
    main()
