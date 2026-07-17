"""
Recompute backtest summaries from the already-saved CSV files (no API calls),
and dump them to results_summary.json for the PPT builder.
"""
import glob, json, os
import pandas as pd

EMA_FAST, EMA_MID, EMA_SLOW = 8, 24, 72
VOL_LB, VOL_RATIO = 20, 1.3
HORIZONS = [3, 6, 12, 24]


def signals(df):
    df = df.copy()
    df["ema8"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema24"] = df["close"].ewm(span=EMA_MID, adjust=False).mean()
    df["ema72"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    df["bull"] = (df["ema8"] > df["ema24"]) & (df["ema24"] > df["ema72"])
    df["bear"] = (df["ema8"] < df["ema24"]) & (df["ema24"] < df["ema72"])
    df["fbull"] = df["bull"] & ~df["bull"].shift(1).fillna(False)
    df["fbear"] = df["bear"] & ~df["bear"].shift(1).fillna(False)
    df["avgv"] = df["volume"].rolling(VOL_LB).mean()
    df["vr"] = df["volume"] / df["avgv"]
    df["vc"] = df["vr"] >= VOL_RATIO
    return df


def fwd(df, col, direction):
    out = []
    for i in df.index[df[col]]:
        e = df.loc[i, "close"]
        if e <= 0:
            continue
        row = {}
        for h in HORIZONS:
            j = i + h
            row[h] = ((df.loc[j, "close"] - e) / e * 100) * direction if j < len(df) else None
        out.append(row)
    return out


def stat(trades, h=6):
    vals = [t[h] for t in trades if t.get(h) is not None]
    if not vals:
        return None
    wins = [v for v in vals if v > 0]
    return {
        "signals": len(vals),
        "win_rate": round(len(wins) / len(vals) * 100, 1),
        "avg_ret": round(sum(vals) / len(vals), 3),
    }


def analyze(path, use_vol=True):
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df = signals(df)
    if use_vol:
        b = df["fbull"] & df["vc"]
        s = df["fbear"] & df["vc"]
    else:
        b, s = df["fbull"], df["fbear"]
    return {
        "candles": len(df),
        "bull": {h: stat(fwd(df.assign(x=b), "x", +1), h) for h in HORIZONS},
        "bear": {h: stat(fwd(df.assign(x=s), "x", -1), h) for h in HORIZONS},
    }


def main():
    res = {"daily_spot": {}, "options": {}, "meta": {}}

    # daily spot: indices (no vol) + stocks (vol)
    for name, fn, uv in [("NIFTY", "nifty_daily.csv", False),
                          ("BANKNIFTY", "banknifty_daily.csv", False)]:
        if os.path.exists(fn):
            res["daily_spot"][name] = analyze(fn, use_vol=uv)

    for fn in sorted(glob.glob("nifty50_*_daily.csv")):
        sym = fn.replace("nifty50_", "").replace("_daily.csv", "").upper()
        res["daily_spot"][sym] = analyze(fn, use_vol=True)

    # options
    for name, fn in [("NIFTY_CALL", "nifty_atm_call_5min.csv"),
                     ("NIFTY_PUT", "nifty_atm_put_5min.csv"),
                     ("BANKNIFTY_CALL", "banknifty_atm_call_5min.csv"),
                     ("BANKNIFTY_PUT", "banknifty_atm_put_5min.csv")]:
        if os.path.exists(fn):
            res["options"][name] = analyze(fn, use_vol=True)

    json.dump(res, open("results_summary.json", "w"), indent=2, default=str)
    print("wrote results_summary.json")

    # quick ranking print for daily spot bull @ +6d, min 5 signals
    ranking = []
    for sym, r in res["daily_spot"].items():
        for side in ("bull", "bear"):
            st = r[side].get(6)
            if st and st["signals"] >= 5:
                ranking.append((sym, side, st["signals"], st["win_rate"], st["avg_ret"]))
    ranking.sort(key=lambda x: (x[3], x[4]), reverse=True)
    print("\nTOP daily-spot by win rate (+6d, n>=5):")
    for r in ranking[:12]:
        print(f"  {r[0]:<12}{r[1]:<6} n={r[2]:<4} WR={r[3]}%  avg={r[4]:+}%")


if __name__ == "__main__":
    main()
