"""
ema_stack_backtest_options.py
------------------------------
Backtests the EMA 8/24/72 stack crossover on ROLLING ATM OPTION 5-min data
fetched from Dhan's expired-options endpoint (requires dhanhq >= 2.3.0rc1).

Covers, for both NIFTY (id 13) and BANK NIFTY (id 25):
  - Monthly ATM CALL
  - Monthly ATM PUT

"Rolling ATM" = each expiry cycle's at-the-money contract stitched together,
so this reflects how an ATM option premium actually behaves intraday.

Data window: last ~6 months, pulled in <=28-day chunks (API caps at 30 days
per call). 5-min interval.

USAGE:
    python ema_stack_backtest_options.py

Output:
    dhan_options_backtest.xlsx  (raw 5-min candles per option leg)
    console win-rate report
"""

import datetime as dt
import time
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

from dhanhq import DhanContext, dhanhq

# ---------------------------------------------------------------------------
import os

# Set these as environment variables before running:
#   Windows PowerShell:  $env:DHAN_CLIENT_ID="your_id"; $env:DHAN_ACCESS_TOKEN="your_token"
CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "YOUR_CLIENT_ID")
ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "YOUR_ACCESS_TOKEN")

CALL_DELAY = 1.2
MONTHS_BACK = 6
CHUNK_DAYS = 28

# underlying id (index id), used with segment NSE_FNO + instrument OPTIDX
UNDERLYINGS = {"NIFTY": "13", "BANKNIFTY": "25"}
OPTION_TYPES = ["CALL", "PUT"]

# ---------------------------------------------------------------------------
EMA_FAST, EMA_MID, EMA_SLOW = 8, 24, 72
VOLUME_LOOKBACK = 20
VOLUME_CONFIRM_RATIO = 1.3
HORIZONS = [3, 6, 12, 24]   # candles (15/30/60/120 min on 5-min chart)


# ---------------------------------------------------------------------------
def _client():
    return dhanhq(DhanContext(CLIENT_ID, ACCESS_TOKEN))


def _call_with_retry(fn, attempts=4, base_delay=2.0):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if "DH-904" in str(e) and i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
                continue
            raise


def fetch_rolling_option(name, security_id, opt_type):
    """Fetch last MONTHS_BACK months of rolling ATM option 5-min candles."""
    d = _client()
    end = dt.date.today()
    start = end - dt.timedelta(days=MONTHS_BACK * 30)

    frames = []
    cur = start
    while cur < end:
        chunk_end = min(cur + dt.timedelta(days=CHUNK_DAYS), end)
        time.sleep(CALL_DELAY)
        resp = _call_with_retry(lambda: d.expired_options_data(
            security_id=security_id,
            exchange_segment="NSE_FNO",
            instrument_type="OPTIDX",
            expiry_flag="MONTH",
            expiry_code=1,
            strike="ATM",
            drv_option_type=opt_type,
            required_data=["open", "high", "low", "close", "volume"],
            from_date=cur.strftime("%Y-%m-%d"),
            to_date=chunk_end.strftime("%Y-%m-%d"),
            interval=5,
        ))
        leg = "ce" if opt_type == "CALL" else "pe"
        payload = resp.get("data", {})
        # response nests as data -> data -> ce/pe
        inner = payload.get("data", payload) if isinstance(payload, dict) else {}
        node = inner.get(leg) if isinstance(inner, dict) else None
        if node and node.get("close"):
            frames.append(pd.DataFrame({
                "timestamp": pd.to_datetime(pd.to_numeric(node["timestamp"]), unit="s"),
                "open": pd.to_numeric(node["open"]),
                "high": pd.to_numeric(node["high"]),
                "low": pd.to_numeric(node["low"]),
                "close": pd.to_numeric(node["close"]),
                "volume": pd.to_numeric(node["volume"]),
            }))
        cur = chunk_end

    if not frames:
        raise RuntimeError(f"{name} {opt_type}: no data")
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    return df


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
        if entry <= 0:
            continue
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
        print("  No signals fired.")
        return
    for h in horizons:
        v = trades[f"ret_{h}"].dropna()
        if v.empty:
            continue
        wr = (v > 0).mean() * 100
        print(f"  +{h}c ({h*5}min): WR {wr:5.1f}% | avg {v.mean():+.3f}% | "
              f"win {(v[v>0].mean() if (v>0).any() else 0):+.3f}% | "
              f"loss {(v[v<=0].mean() if (v<=0).any() else 0):+.3f}% (n={len(v)})")
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
def main():
    sheets = {}
    for name, sid in UNDERLYINGS.items():
        for opt in OPTION_TYPES:
            label = f"{name}_ATM_{opt}"
            try:
                print(f"[+] Fetching {label} rolling 5-min ...")
                df = fetch_rolling_option(name, sid, opt)
                print(f"    {len(df)} candles ({df['timestamp'].min()} -> {df['timestamp'].max()})")
                sheets[label] = df
                df.to_csv(f"{label.lower()}_5min.csv", index=False)
                run_one(label, df)
            except Exception as e:
                print(f"  {label} failed: {e}")

    excel = "dhan_options_backtest.xlsx"
    with pd.ExcelWriter(excel, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name[:31], index=False)
    print(f"\n[+] Excel -> {excel}  ({len(sheets)} sheets)")


if __name__ == "__main__":
    main()
