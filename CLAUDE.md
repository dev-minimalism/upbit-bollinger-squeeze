# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Korean-language crypto signal bot for the Upbit KRW market. It computes a "volatility squeeze + Bollinger Band" strategy on daily candles and pushes buy/sell alerts to Telegram. There are two independent halves: a long-running realtime monitor (the production path) and a standalone backtester.

## Commands

```bash
# Setup. Python is pinned to 3.13 in .python-version; the pinned pandas/numpy have no 3.14 wheels.
uv venv --python 3.13 .venv            # or: python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Tests (synthetic DataFrames only, no network)
pytest
pytest tests/test_indicators.py::test_monitor_and_backtest_indicators_agree   # single test

# Format and lint (ruff, configured in pyproject.toml)
ruff format .
ruff check .

# REQUIRED before running the monitor: logging.FileHandler in upbit_main.py opens
# upbit_output_files/logs/... at import time and crashes if the directory is missing.
mkdir -p upbit_output_files/logs

# Run the realtime monitor (foreground)
python upbit_main.py --mode monitor-default

# Run it in the background (from README.md)
nohup python upbit_main.py --mode monitor-default > upbit_output_files/logs/nohup.out 2>&1 &

# Stop it
kill -TERM <PID>   # or Ctrl+C in the foreground

# Run the backtester (interactive: prompts for initial capital in KRW)
python upbit_backtest_strategy.py
```

Environment variables:

| Variable | Purpose |
|---|---|
| `UPBIT_BOLLINGER_TELEGRAM_BOT_TOKEN` | Telegram bot token. Without it the monitor runs but alerts are only logged. |
| `UPBIT_BOLLINGER_TELEGRAM_CHAT_ID` | Chat that receives alerts. |
| `UPBIT_ACCESS_KEY` / `UPBIT_SECRET_KEY` | Optional. Only the backtester instantiates `pyupbit.Upbit` with them; the monitor uses the public API regardless. |

## Known problems (verified, not yet fixed)

- `upbit_main.py --mode backtest` is accepted by argparse but exits with "unsupported mode". The main file only wires the monitor and never imports the backtest module. The docstring also mentions `monitor` and `both` modes that do not exist.
- `setup_korean_font()` in the backtester calls `fm._rebuild()`, which matplotlib removed in 3.6. On the pinned 3.10.5 this raises, the outer `except` overwrites the already-set Korean font with DejaVu Sans, and chart labels render as boxes.
- `ruff check` currently reports 26 findings (f-strings without placeholders, unused variables, two bare `except`). They are deliberately left for the cleanup pass; do not widen the lint rule set until they are gone.

## Architecture

Three flat modules, no package:

- `upbit_main.py` configures root logging (DEBUG, file + stdout), sets the macOS Korean font for matplotlib, builds `UpbitRealTimeVolatilityMonitor`, and calls `start_monitoring(scan_interval=300)`.
- `upbit_realtime_monitor.py` holds the monitor class and all Telegram handling.
- `upbit_backtest_strategy.py` holds `UpbitVolatilityBollingerBacktest` and is fully self-contained (own font setup, own output dirs, own coin list). Importing it runs `setup_korean_font()` as a side effect.

### Threading model of the monitor

`start_monitoring()` spawns three threads and then **blocks by joining the monitor thread**:

1. Telegram bot thread (daemon): runs `Application.run_polling(stop_signals=None)` on a fresh asyncio loop. `stop_signals=None` is required because signal handlers can only be installed on the main thread. This thread handles inbound `/start`, `/ticker <SYM>`, `/status` commands only.
2. Heartbeat thread (daemon): sends a status message every hour.
3. Monitor thread (non-daemon): loops over `self.watchlist`, calls `check_signals` per coin with a 0.2s pause, sleeps `scan_interval`, and sends a status summary every 5th scan. Any exception inside the loop is caught and retried after 30s, so the process effectively never dies on data errors.

**Outbound alerts do not go through the Application.** `send_telegram_alert` does a raw `requests.post` to the Bot API `sendMessage` endpoint with `parse_mode=HTML`. Keep that split in mind: inbound = python-telegram-bot, outbound = requests.

Alert dedup lives in `should_send_alert`: key is `{symbol}_{signal_type}`, cooldown is 3600s. `total_signals_sent` and `last_signal_time` are only updated when the HTTP send succeeds.

### Strategy semantics (shared by both halves)

Indicators are computed on daily OHLCV from `pyupbit.get_ohlcv(interval="day")`. The monitor fetches 100 candles; the backtester asks for ~1100 with a retry/fallback ladder.

- `Band_Width = (Upper - Lower) / SMA` with BB(20, 2.0).
- `Volatility_Squeeze = Band_Width < rolling(50).quantile(0.2)` of itself. Because it is a relative quantile, roughly 20% of days in any steady regime are flagged; the flag is meaningful only when volatility has just dropped relative to the prior 50 days.
- `BB_Position = (close - Lower) / (Upper - Lower)`, 0 to 1.
- `Buy_Signal = RSI > overbought AND Volatility_Squeeze`. The buy condition deliberately fires on **overbought** RSI inside a squeeze (momentum breakout). Do not "fix" it to oversold.
- `Sell_50_Signal = BB_Position >= sell_threshold OR |BB_Position - 0.5| <= 0.1` (near upper band, or back at the midband).
- `Sell_All_Signal = BB_Position <= sell_all_threshold`.

The indicator code is **duplicated** in `calculate_indicators` (monitor) and `calculate_technical_indicators` (backtest). Any change to the formula must be applied to both. `tests/test_indicators.py` asserts the two produce identical output; that test is the guardrail for merging them. The monitor hardcodes the "conservative" thresholds (RSI 70, sell 0.8, sell-all 0.1); the backtester exposes `strategy_mode` = conservative / balanced / aggressive via `_setup_parameters`.

Backtest position state machine in `_execute_backtest`: `0` flat, `2` full, `1` half. Buy only from 0 and goes all-in to 2. Sell_50 only from 2, moves to 1. Sell_All from any position > 0, back to 0. Open positions are liquidated at the last close. `_analyze_trades` pairs each SELL with the most recent BUY, so one buy can produce two completed-trade rows (a 50% exit and a full exit). `tests/test_backtest.py` pins this behaviour.

### Coin lists are coupled

The monitor keeps two parallel structures in `__init__`: `self.watchlist` (list of `KRW-XXX` tickers that get scanned) and `self.ticker_to_korean` (ticker to Korean display name, used in alert text). Adding or removing a coin means editing both; a missing mapping silently falls back to the raw ticker. The backtester has its own much shorter `self.crypto_list`, independent of the monitor.

### Output files

Everything lands under `upbit_output_files/` (gitignored): `logs/` (monitor, created manually), `results/` CSV, `charts/` PNG at 300 dpi, `reports/` TXT. Only the backtester creates its own subdirectories; tests stub that out so they never write to the repo.

## Conventions

- Formatting is `ruff format` (4-space indent, double quotes, line length 100). Run it before committing.
- Comments, docstrings, log messages, and user-facing strings are in Korean with heavy emoji. Keep new output in the same style.
- Telegram messages use HTML parse mode; escape `<` and `>` as `&lt;` / `&gt;` in message text.
- Every method swallows exceptions and logs them rather than raising. The monitor is designed to never crash.
- Tests build small synthetic OHLCV DataFrames and never touch the network. Construct the monitor with no token and stub `_setup_output_directories` on the backtester (see `tests/conftest.py`).
