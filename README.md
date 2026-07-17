# EMA 8/24/72 Stack Strategy — Backtest on NIFTY 50, Bank Nifty & ATM Options

> **Free intraday & daily OHLCV data + a fully documented Python backtest of the
> EMA 8/24/72 stack crossover strategy on Indian markets (NSE).**
> Includes something most sites *don't* give away for free — **historical ATM
> options data (rolling Call/Put) for Nifty & Bank Nifty.**

Built with real market data pulled from the **DhanHQ API**.

---

## What is inside

- **EMA stack crossover strategy** (8 / 24 / 72 EMAs) with volume confirmation
- **Backtest scripts** for:
  - Nifty 50 index & Bank Nifty index
  - All 48 liquid **Nifty 50 constituent stocks**
  - **Rolling ATM options** (Call & Put) for Nifty and Bank Nifty
- **Ready-to-use data**: 5-minute and daily candles in CSV + Excel
- **Results summary** (win rate, average return, per-horizon stats)
- A **PowerPoint** of the results (`EMA_Stack_Backtest_Results.pptx`)

---

## The Strategy (in one line)

Stack three EMAs — **EMA8, EMA24, EMA72**. When they line up
`8 > 24 > 72` it is a **bullish** stack; `8 < 24 < 72` is **bearish**.
A trade "fires" only on the candle the stack *first* forms, and only when that
candle's volume is **>= 1.3x** its 20-bar average. Forward returns are then
measured at **+3 / +6 / +12 / +24** bars (or trading days).

---

## Headline Results

### Stocks & Indices (daily candles, 3.5 years, +6 trading days, min 5 signals)

| Symbol | Side | Signals | Win Rate | Avg Return |
|--------|------|--------:|---------:|-----------:|
| TATASTEEL   | BULL | 5  | **100.0%** | +3.77% |
| BAJAJFINSV  | BULL | 5  | 80.0% | +3.31% |
| **BANK NIFTY** | BULL | 16 | **75.0%** | +0.43% |
| ICICIBANK   | BULL | 7  | 71.4% | +0.94% |
| **NIFTY 50**   | BULL | 14 | **71.4%** | +0.57% |
| BPCL        | BULL | 7  | 71.4% | +0.17% |
| HEROMOTOCO  | BULL | 6  | 66.7% | +1.43% |
| ULTRACEMCO  | BULL | 6  | 66.7% | +0.92% |

> The **indices** (Bank Nifty, Nifty) have the biggest signal counts, so their
> win rates are the most trustworthy. On the **buy side**, the EMA stack shows a
> real statistical edge.

### Options (rolling ATM, 6 months of 5-min data, +120 min hold)

| Option Leg | Best Side | Signals | Win Rate | Avg Return |
|-----------|-----------|--------:|---------:|-----------:|
| BANK NIFTY PUT  | BEAR | 59  | **59.3%** | +2.09% |
| BANK NIFTY CALL | BEAR | 77  | 46.8% | +1.83% |
| NIFTY CALL      | BEAR | 108 | 42.6% | +0.23% |
| NIFTY PUT       | BEAR | 99  | 42.4% | +0.45% |

> **Reality check:** *Buying* options on this signal loses money on almost every
> leg (win rate 12–33%, negative average return) because of theta decay and
> whipsaw. Take the EMA-stack signal on **spot / futures**, and use options only
> to execute — not as the thing you measure the signal on.

---

## Repository Structure

```
ema_stack_backtest.py            # Base backtest (runs on any 5-min OHLCV CSV)
ema_stack_backtest_dhan.py       # Fetch 5-min data from Dhan + backtest
ema_stack_backtest_dhan_full.py  # Bank Nifty + ATM option + all Nifty50 stocks (5-min)
ema_stack_backtest_daily.py      # 3.5-year daily backtest + ranking
ema_stack_backtest_options.py    # Rolling ATM Call/Put options backtest
build_summary.py                 # Recompute stats from saved CSVs -> results_summary.json
build_ppt.py                     # Build the PowerPoint report

data/  (CSV files)               # 5-min & daily candles for every instrument
*.xlsx                           # Excel workbooks (one sheet per instrument)
results_summary.json             # Machine-readable results
```

---

## How to Run It Yourself

1. Install dependencies:
   ```bash
   pip install --pre dhanhq==2.3.0rc1 pandas openpyxl python-pptx
   ```
2. Set your **own** Dhan API credentials as environment variables (never hard-code them):
   ```powershell
   $env:DHAN_CLIENT_ID="your_client_id"
   $env:DHAN_ACCESS_TOKEN="your_access_token"
   ```
   Get a free API token from your Dhan account: <https://dhanhq.co>
3. Run any backtest:
   ```bash
   python ema_stack_backtest_daily.py      # stocks + indices (daily)
   python ema_stack_backtest_options.py    # ATM options (5-min)
   ```

---

## Searchable topics this repo covers

`nifty 50 historical data free` · `bank nifty option historical data` ·
`nifty 5 minute data csv` · `EMA crossover strategy backtest India` ·
`8 24 72 EMA strategy` · `dhan api python backtest` ·
`atm option premium historical data` · `nifty options backtesting python` ·
`intraday trading strategy win rate` · `algo trading India open source`

---

## Disclaimer

**This project is for educational and research purposes only.** It is **not**
investment advice, a recommendation, or a solicitation to trade. Past backtested
performance does **not** guarantee future results. Trading in equities,
derivatives and options carries substantial risk of loss. Do your own research
and consult a SEBI-registered advisor before trading. The author is not liable
for any losses arising from use of this code or data. Market data belongs to its
respective exchanges/providers and is shared here for educational study only.

## License

Released under the [MIT License](LICENSE) — free to use, modify and share.
