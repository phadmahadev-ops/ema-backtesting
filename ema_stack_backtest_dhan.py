"""
ema_stack_backtest_dhan.py
--------------------------
Fetches 5-minute OHLCV candles DIRECTLY from the Dhan API for:
    - NIFTY 50 (index, ID 13)
    - RELIANCE (NSE equity, ID 1333)
    - MARUTI   (NSE equity, ID 10999)
then runs the 8/24/72 EMA stack crossover backtest and reports win rate,
avg return, avg winner/loser and max adverse excursion per horizon.

The data is also exported to an Excel file (one sheet per symbol) so you
can inspect/reuse it.

USAGE:
    python ema_stack_backtest_dhan.py

Outputs:
    - <symbol>_5min.xlsx  (raw candles, one sheet per symbol)
    - console backtest report with win rates

Requires: dhanhq, pandas, openpyxl  (pip install dhanhq pandas openpyxl)
"""

import datetime as dt
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

from dhanhq import dhanhq

# ---------------------------------------------------------------------------
# Dhan credentials (from the token you provided)
# ---------------------------------------------------------------------------
import os

# Set these as environment variables before running:
#   Windows PowerShell:  $env:DHAN_CLIENT_ID="your_id"; $env:DHAN_ACCESS_TOKEN="your_token"
CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "YOUR_CLIENT_ID")
ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "YOUR_ACCESS_TOKEN")

# How many trading days of 5-min history to pull (Dhan caps intraday at ~5 days)
LOOKBACK_DAYS = 5

# symbol -> (security_id, exchange_segment, instrument_type)
INSTRUMENTS = {
    "NIFTY":    ("13",   "IDX_I",  "INDEX"),
    "RELIANCE": ("1333", "NSE_EQ", "EQUITY"),
    "MARUTI":   ("10999", "NSE_EQ", "EQUITY"),
}

# ---------------------------------------------------------------------------
# Backtest config (same as ema_stack_backtest.py)
# ---------------------------------------------------------------------------
EMA_FAST, EMA_MID, EMA_SLOW = 8, 24, 72
VOLUME_LOOKBACK = 20
VOLUME_CONFIRM_RATIO = 1.3
HORIZONS = [3, 6, 12, 24]   # candles ahead (15/30/60/120 min on 5-min chart)


# ---------------------------------------------------------------------------
# Fetch from Dhan
# ---------------------------------------------------------------------------
def fetch_5min(symbol: str, security_id: str, segment: str, instrument: str) -> pd.DataFrame:
    d = dhanhq(CLIENT_ID, ACCESS_TOKEN)

    to_date = dt.date.today()
    from_date = to_date - dt.timedelta(days=LOOKBACK_DAYS)

    resp = d.intraday_minute_data(
        security_id, segment, instrument,
        from_date.strftime("%Y-%m-%d"),
        to_date.strftime("%Y-%m-%d"),
        interval=5,
    )

    if resp.get("status") != "success":
        raise RuntimeError(f"{symbol}: Dhan API error -> {resp.get('remarks')}")

    data = resp["data"]
    n = len(data.get("timestamp", []))
    if n == 0:
        raise RuntimeError(
            f"{symbol}: no candles returned (empty). "
            f"Check that {from_date}..{to_date} includes trading days."
        )

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
# Signals + backtest (reused logic)
# ---------------------------------------------------------------------------
def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
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


def forward_returns(df: pd.DataFrame, signal_col: str, direction: int, horizons: list) -> pd.DataFrame:
    rows = []
    idxs = df.index[df[signal_col]].tolist()

    for i in idxs:
        entry_price = df.loc[i, "close"]
        row = {"entry_idx": i, "entry_ts": df.loc[i, "timestamp"], "entry_price": entry_price,
               "vol_ratio": df.loc[i, "vol_ratio"]}

        for h in horizons:
            exit_idx = i + h
            if exit_idx >= len(df):
                row[f"ret_{h}"] = float("nan")
                continue
            exit_price = df.loc[exit_idx, "close"]
            ret_pct = ((exit_price - entry_price) / entry_price * 100) * direction
            row[f"ret_{h}"] = ret_pct

        max_h = max(horizons)
        window = df.loc[i:min(i + max_h, len(df) - 1)]
        if direction == 1:
            worst = ((window["low"].min() - entry_price) / entry_price * 100)
        else:
            worst = ((entry_price - window["high"].max()) / entry_price * 100)
        row["max_adverse_pct"] = worst

        rows.append(row)

    return pd.DataFrame(rows)


def summarize(trades: pd.DataFrame, horizons: list, label: str):
    print(f"\n{'='*60}")
    print(f"  {label}  -  {len(trades)} signals")
    print(f"{'='*60}")

    if trades.empty:
        print("  No signals fired in this dataset.")
        return

    for h in horizons:
        col = f"ret_{h}"
        valid = trades[col].dropna()
        if valid.empty:
            continue
        win_rate = (valid > 0).mean() * 100
        avg_ret = valid.mean()
        avg_win = valid[valid > 0].mean() if (valid > 0).any() else 0
        avg_loss = valid[valid <= 0].mean() if (valid <= 0).any() else 0
        minutes = h * 5
        print(f"  Horizon +{h} candles ({minutes}min):  "
              f"Win rate {win_rate:5.1f}%  |  Avg return {avg_ret:+.3f}%  |  "
              f"Avg win {avg_win:+.3f}%  |  Avg loss {avg_loss:+.3f}%  (n={len(valid)})")

    avg_adverse = trades["max_adverse_pct"].mean()
    print(f"  Avg max adverse excursion: {avg_adverse:+.3f}%")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    excel_path = "dhan_5min_data.xlsx"
    all_sheets = {}

    for symbol, (sid, seg, inst) in INSTRUMENTS.items():
        print(f"\n[+] Fetching 5-min data for {symbol} (id={sid}) ...")
        df = fetch_5min(symbol, sid, seg, inst)
        print(f"    Got {len(df)} candles  ({df['timestamp'].min()} -> {df['timestamp'].max()})")

        all_sheets[symbol] = df
        df.to_csv(f"{symbol.lower()}_5min.csv", index=False)

        df = compute_signals(df)

        # WITH volume confirmation
        bull_confirmed = df["fresh_bull"] & df["vol_confirmed"]
        bear_confirmed = df["fresh_bear"] & df["vol_confirmed"]
        bull_trades = forward_returns(df.assign(sig=bull_confirmed), "sig", +1, HORIZONS)
        bear_trades = forward_returns(df.assign(sig=bear_confirmed), "sig", -1, HORIZONS)
        summarize(bull_trades, HORIZONS, f"{symbol} - BULL stack (volume confirmed)")
        summarize(bear_trades, HORIZONS, f"{symbol} - BEAR stack (volume confirmed)")

        # WITHOUT volume confirmation (for comparison)
        bull_raw = forward_returns(df.assign(sig=df["fresh_bull"]), "sig", +1, HORIZONS)
        bear_raw = forward_returns(df.assign(sig=df["fresh_bear"]), "sig", -1, HORIZONS)
        summarize(bull_raw, HORIZONS, f"{symbol} - BULL stack (NO volume filter)")
        summarize(bear_raw, HORIZONS, f"{symbol} - BEAR stack (NO volume filter)")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        for symbol, df in all_sheets.items():
            df.to_excel(writer, sheet_name=symbol, index=False)

    print(f"\n[+] Excel exported -> {excel_path}")


if __name__ == "__main__":
    main()
