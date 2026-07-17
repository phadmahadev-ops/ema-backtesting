"""
ema_stack_backtest.py
----------------------
Backtests the 8/24/72 EMA stack crossover strategy (same logic as
ema_trend_engine.py) on historical 5-min candles, so you can decide
whether it's actually profitable BEFORE wiring it into live alerts.

USAGE:
    python ema_stack_backtest.py --csv nifty_5min.csv --symbol NIFTY

CSV format expected (columns, any order):
    timestamp, open, high, low, close, volume

Get this data from your Dhan historical candle API
(same one your backtesting module already uses for NSE stocks) —
export it to CSV first, or adapt `load_data()` below to pull directly.

WHAT IT MEASURES:
- Every time a fresh bullish/bearish stack forms (with volume confirm),
  it measures forward return over multiple horizons (3, 6, 12, 24 candles
  = 15min, 30min, 1hr, 2hr on 5-min chart).
- Reports win rate, avg return, avg winner, avg loser, max drawdown per
  trade, and total signal count.
- Also runs a NO-volume-filter version side by side so you can see if
  the volume confirmation is actually helping or just cutting signal count.
"""

import argparse
import numpy as np
import pandas as pd

EMA_FAST, EMA_MID, EMA_SLOW = 8, 24, 72
VOLUME_LOOKBACK = 20
VOLUME_CONFIRM_RATIO = 1.3
HORIZONS = [3, 6, 12, 24]   # candles ahead to measure forward return


def load_data(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = [c.strip().lower() for c in df.columns]
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {missing}")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


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
    """direction: +1 for bull (long), -1 for bear (short)"""
    rows = []
    idxs = df.index[df[signal_col]].tolist()

    for i in idxs:
        entry_price = df.loc[i, "close"]
        row = {"entry_idx": i, "entry_ts": df.loc[i, "timestamp"], "entry_price": entry_price,
               "vol_ratio": df.loc[i, "vol_ratio"]}

        for h in horizons:
            exit_idx = i + h
            if exit_idx >= len(df):
                row[f"ret_{h}"] = np.nan
                continue
            exit_price = df.loc[exit_idx, "close"]
            ret_pct = ((exit_price - entry_price) / entry_price * 100) * direction
            row[f"ret_{h}"] = ret_pct

        # max adverse move within the largest horizon window (rough drawdown proxy)
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
    print(f"  {label}  —  {len(trades)} signals")
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


def run_backtest(csv_path: str, symbol: str):
    df = load_data(csv_path)
    df = compute_signals(df)

    print(f"\nLoaded {len(df)} candles for {symbol} "
          f"({df['timestamp'].min()} to {df['timestamp'].max()})")

    # --- WITH volume confirmation (what ema_trend_engine.py actually fires) ---
    bull_confirmed = df["fresh_bull"] & df["vol_confirmed"]
    bear_confirmed = df["fresh_bear"] & df["vol_confirmed"]

    bull_trades = forward_returns(df.assign(sig=bull_confirmed), "sig", +1, HORIZONS)
    bear_trades = forward_returns(df.assign(sig=bear_confirmed), "sig", -1, HORIZONS)

    summarize(bull_trades, HORIZONS, f"{symbol} — BULL stack (volume confirmed)")
    summarize(bear_trades, HORIZONS, f"{symbol} — BEAR stack (volume confirmed)")

    # --- WITHOUT volume confirmation, for comparison ---
    bull_raw = forward_returns(df.assign(sig=df["fresh_bull"]), "sig", +1, HORIZONS)
    bear_raw = forward_returns(df.assign(sig=df["fresh_bear"]), "sig", -1, HORIZONS)

    summarize(bull_raw, HORIZONS, f"{symbol} — BULL stack (NO volume filter, for comparison)")
    summarize(bear_raw, HORIZONS, f"{symbol} — BEAR stack (NO volume filter, for comparison)")

    print(f"\n{'='*60}")
    print("  VERDICT GUIDE")
    print(f"{'='*60}")
    print("  - Look at the 30min-1hr horizon (6-12 candles) — that's the")
    print("    realistic holding window for an intraday trend alert.")
    print("  - Win rate > 55% AND avg return clearly positive after both")
    print("    directions = signal has edge, safe to deploy publicly.")
    print("  - Win rate ~50% or avg return near zero = EMA stack alone is")
    print("    NOT enough, needs an extra filter (e.g. only trade with")
    print("    overall NIFTY trend, or add RSI/ADX confirmation) before")
    print("    going public — publishing a coinflip signal will hurt trust.")
    print("  - Compare confirmed vs no-filter results — if volume filter")
    print("    isn't clearly improving win rate, it's just cutting alert")
    print("    frequency for no benefit and can be dropped or adjusted.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Path to 5-min OHLCV CSV")
    parser.add_argument("--symbol", default="NIFTY")
    args = parser.parse_args()
    run_backtest(args.csv, args.symbol)
