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

# Run the realtime monitor (foreground). The log directory is created on start.
python upbit_main.py                                   # --mode monitor is the default
python upbit_main.py --strategy balanced               # conservative | balanced | aggressive

# Background. The shell opens the redirect target before Python runs, so create the directory first.
mkdir -p upbit_output_files/logs
nohup python upbit_main.py > upbit_output_files/logs/nohup.out 2>&1 &
kill -TERM <PID>                                       # stop; Ctrl+C in the foreground

# Backtest through the same entry point (non-interactive)
python upbit_main.py --mode backtest --capital 1000000 --days 1095 --strategy aggressive
python upbit_main.py --mode backtest --days 120        # end-to-end smoke, ~10s, hits the public Upbit API

# The backtester's own main() still exists and prompts for capital interactively
python upbit_backtest_strategy.py
```

Environment variables:

| Variable | Purpose |
|---|---|
| `UPBIT_BOLLINGER_TELEGRAM_BOT_TOKEN` | Telegram bot token. Without it the monitor runs but alerts are only logged. |
| `UPBIT_BOLLINGER_TELEGRAM_CHAT_ID` | Chat that receives alerts. |
| `UPBIT_ACCESS_KEY` / `UPBIT_SECRET_KEY` | Optional. Only the backtester instantiates `pyupbit.Upbit` with them; the monitor uses the public API regardless. |

## Known problems (verified, not yet fixed)

- `ruff check` currently reports 25 findings (f-strings without placeholders, unused variables, two bare `except`). They are deliberately left for the cleanup pass; do not widen the lint rule set until they are gone.

## Architecture

Four flat modules, no package:

- `strategy.py` is the single definition of the strategy: `StrategyParams` (frozen dataclass), the `STRATEGY_PRESETS` dict (conservative / balanced / aggressive), and `compute_indicators(df, params)`. Change the formula or thresholds here and nowhere else.
- `upbit_main.py` is the argparse entry point: `parse_args` (accepts `monitor-default` as an alias for `monitor`), `run_monitor`, `run_backtest`. Logging is configured only in monitor mode by `setup_logging`, at INFO with `httpx`/`httpcore` raised to WARNING because Telegram polling makes one request per second. The backtester is imported lazily inside `run_backtest` so the monitor process never loads matplotlib. Importing the module has no side effects; `tests/test_main.py` depends on that.
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

The formula lives only in `compute_indicators` in `strategy.py`; it returns a new frame and never mutates its input. `calculate_indicators` (monitor) and `calculate_technical_indicators` (backtest) are one-line wrappers that pass `self.params`. The monitor takes an optional `params` constructor argument and defaults to the conservative preset; the backtester resolves `strategy_mode` through `StrategyParams.from_mode`, which raises `ValueError` on an unknown mode. `tests/test_indicators.py` still asserts the two wrappers agree, and `tests/test_strategy.py` checks that each preset's thresholds reach the signal columns.

Backtest position state machine in `_execute_backtest`: `0` flat, `2` full, `1` half. Buy only from 0 and goes all-in to 2. Sell_50 only from 2, moves to 1. Sell_All from any position > 0, back to 0. Open positions are liquidated at the last close. `_analyze_trades` pairs each SELL with the most recent BUY, so one buy can produce two completed-trade rows (a 50% exit and a full exit). `tests/test_backtest.py` pins this behaviour.

### Coin lists are coupled

The monitor keeps two parallel structures in `__init__`: `self.watchlist` (list of `KRW-XXX` tickers that get scanned) and `self.ticker_to_korean` (ticker to Korean display name, used in alert text). Adding or removing a coin means editing both; a missing mapping silently falls back to the raw ticker. The backtester has its own much shorter `self.crypto_list`, independent of the monitor.

### Output files

Everything lands under `upbit_output_files/` (gitignored, anchored to the file's directory, not the CWD): `logs/` (created by `setup_logging` on monitor start), `results/` CSV, `charts/` PNG at 300 dpi, `reports/` TXT. The backtester creates its own subdirectories; tests stub that out so they never write to the repo.

## Conventions

- Formatting is `ruff format` (4-space indent, double quotes, line length 100). Run it before committing.
- Comments, docstrings, log messages, and user-facing strings are in Korean with heavy emoji. Keep new output in the same style.
- Telegram messages use HTML parse mode; escape `<` and `>` as `&lt;` / `&gt;` in message text.
- Every method swallows exceptions and logs them rather than raising. The monitor is designed to never crash.
- Tests build small synthetic OHLCV DataFrames and never touch the network. The shared `breakout_df` fixture (100 days of high-volatility oscillation, then a 30-day gentle ramp) is the one series where both buy conditions hold; reuse it before inventing another. Construct the monitor with no token and stub `_setup_output_directories` on the backtester (see `tests/conftest.py`).
