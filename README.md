# HK Quote

A local Python dashboard for monitoring Hong Kong and US stocks through Futu OpenD. It combines live quotes, volume-and-price alerts, Hong Kong broker activity analysis, and historical records in a SQLite-backed application.

The interface is primarily in Chinese. This is a read-only market data tool; it does not place orders.

## Features

- **Live quotes and charts:** streaming prices, percentage changes, intraday price and volume charts, expandable charts with hover details, and on-demand daily candlesticks.
- **Volume-and-price alerts:** identify unusually large turnover accompanied by rapid, sustained upward or downward price movement across 3-, 15-, and 60-second windows.
- **Watchlist management:** search by name or symbol, add or remove stocks, start or stop monitoring individually, and choose a default stock. Hong Kong watchlists can be imported manually from Futu groups.
- **Order books:** show available bid/ask levels, aggregate shares and order counts per price level, plus Hong Kong broker queue names and identifiers when available.
- **Hong Kong broker analysis:** capture top-ten net buying/selling snapshots, compare morning and afternoon activity by broker, and inspect broker presence around alerts.
- **Historical review:** paginated and filterable alerts, collapsible evidence panels, stored broker snapshots, date-based analysis, and replay tools.
- **Local notifications and storage:** macOS desktop notifications, a local web dashboard, SQLite persistence, and a Markdown export of alert history.

## Requirements

- Python **3.9 or later**.
- Futu OpenD installed, running, and logged in, with its API listener enabled.
- Market data permissions and subscription quota sufficient for the symbols and data types you use. Available depth and broker data depend on your actual account permissions.
- A modern browser.

The application has been developed and exercised on macOS. Desktop notifications use macOS `osascript`; on other platforms, set `desktop_notifications` to `false`. Other platforms have not been fully validated.

The default OpenD endpoint is `127.0.0.1:11111`. The current connection setup does not expose RSA key configuration.

## Quick start

Run the following commands from the repository root after cloning or downloading the project:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
mkdir -p data
```

Review [config/settings.json](config/settings.json) before the first run, especially the OpenD address, initial stock list, and desktop notification setting.

### 1. Check OpenD

Start and log in to OpenD, then run:

```sh
.venv/bin/hk-quote check
```

This checks the connection and quote login state without subscribing to stock data.

### 2. Start the collector

In one terminal:

```sh
.venv/bin/hk-quote run
```

Leave it running to collect quotes and generate alerts. Use `Ctrl+C` to stop it safely.

The symbols in the configuration seed the watchlist as **enabled on first initialization**. Stocks subsequently added through the dashboard start **stopped**. Once initialized, the saved web watchlist controls monitoring; editing the initial symbol list does not overwrite it.

### 3. Start the dashboard

In a second terminal, also from the repository root:

```sh
.venv/bin/python -m hk_quote.dashboard
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

The dashboard and collector are separate processes. The dashboard can remain available for historical review while collection is stopped or the market is closed. The computer must remain awake for live collection.

The default configuration disables the dashboard password. To enable it, set `dashboard.require_password` to `true`, restart the dashboard, and use the generated password in `data/dashboard-password.txt`.

These commands run in the foreground. They do not install a background service, create PID files, or configure automatic startup.

## Markets and sessions

| Market | Example symbols | Time zone | Supported collection periods |
| --- | --- | --- | --- |
| Hong Kong | `HK.00700`, `HK.02206` | Asia/Hong_Kong | Continuous trading, plus pre-open and closing auction quote display |
| United States | `US.QQQ`, `US.AAPL` | America/New_York | Pre-market, regular trading, and post-market |

Hong Kong rapid-move alerts run during continuous trading; auction quotes are handled separately. Lunch breaks, trading holidays, and half days are handled through the trading calendar and session logic.

US sessions use New York time with daylight saving adjustments: pre-market 04:00–09:30, regular trading 09:30–16:00, and post-market 16:00–20:00. On half days, regular trading ends at 13:00 and this version pauses post-market monitoring. Overnight trading is not monitored. Analysis waits for trading-calendar confirmation.

US quotes run in a separate worker and OpenD context, with separate connection health and session baselines. They share the same database and dashboard. US amounts are in USD, Hong Kong amounts in HKD, and records use the corresponding market's trading date.

US monitoring is an initial implementation. Its available Nasdaq / NYSE Arca data is determined by OpenD permissions and does not represent complete consolidated US market coverage. Hong Kong broker analytics and Stock Connect target prices are not available for US symbols.

## How alerts work

### Rapid volume-and-price moves

The active detector is configured under `rapid_move` in [config/settings.json](config/settings.json). An alert requires **both abnormal turnover and sustained price movement**. High turnover alone does not trigger a new trade alert.

Each stock and trading phase maintains separate 3-, 15-, and 60-second rolling-window baselines:

1. **Turnover:** the current window must reach the historical turnover P95 multiplied by **1.1**.
2. **Price magnitude:** the absolute start-to-end price change must exceed the historical absolute price-change P99 multiplied by **1.25**, or twice the contemporaneous bid/ask spread, whichever is greater. The spread condition is applied only when suitable book data is available.
3. **Price path:** the move must be reasonably direct, with at least three nonzero sampled price changes. Net displacement must be at least **80%** of the total sampled path and **80%** of the price range. A single step cannot account for more than **60%** of the path.

The history horizon is **15 minutes**. Sampling uses interval closing prices to reduce print-to-print noise while preserving the actual start and end prices. Detection and baseline windows have matching lengths; only historical windows ending before the current detection window begins are eligible.

Each scale needs at least **60 eligible samples**, an effective **180-second warmup**, and price observations spanning at least half its window. Missing trades are not filled with synthetic zero-volume samples. Sparse stocks can therefore remain in the sampling state longer.

New alerts are labeled **“放量快速拉升”** (rapid rise with elevated turnover) or **“放量快速下跌”** (rapid decline with elevated turnover). Direction follows the price path; trade-side flags are supplementary. A stock shares a **60-second cooldown per direction** across the three scales.

Alerts retain their turnover threshold, dynamic price threshold, window length, price change, path efficiency, and spread availability. Old alerts retain their original labels and rules. The former fixed 0.1% price filter is not used by the active detector.

These parameters are initial, configurable heuristics. Replay checks behavior against recorded inputs; it does not establish predictive accuracy or trading profitability.

### Behavioral observations

Hong Kong analysis also has a separate observer for suspected selling pressure, absorption/support, and upward pressure. It records observation, confirmation, continuation, and ending states using trade direction, price movement, and order-book evidence.

These observations are distinct from rapid-move alerts and can share linked evidence. Their names describe observed patterns rather than proving a trader's identity or intent. The independent observer is configured under `behavior`.

### Broker evidence

Hong Kong analysis combines two different sources:

- **Broker queues:** broker presence in visible resting orders, including best-bid/best-ask background and changes around alerts.
- **Top-ten net buying/selling snapshots:** cumulative broker statistics queried every **10 seconds** by default. The source may update less frequently than the query interval.

Delayed comparisons use source timestamps and before/after snapshots. Missing brokers are treated as **unknown**, not zero. Overlapping events may share a comparison interval; the same snapshot change is not proof of separate trades in every linked event.

Broker queue presence is not executed volume. Net buying/selling is not a position balance or an individual trade attribution. Channel labels describe a broker's documented business profile, not whether a particular client is an institution or a retail investor.

Snapshots and post-close retrievals are retained when captured. Selecting an earlier date cannot recreate broker data the application never collected.

## Configuration

Edit [config/settings.json](config/settings.json), then restart the affected processes.

| Setting | Purpose |
| --- | --- |
| `host`, `port` | OpenD connection address; defaults to `127.0.0.1:11111` |
| `symbols`, `names` | Initial watchlist and display names |
| `database` | Collector SQLite database path |
| `desktop_notifications` | Enable or disable macOS desktop notifications |
| `dashboard.require_password` | Require dashboard login; currently `false` |
| `broker_stats_seconds` | Hong Kong broker snapshot query interval; currently `10` |
| `cooldown_seconds` | Shared alert cooldown per stock and direction |
| `rapid_move` | Active multi-scale turnover and price-path detection |
| `behavior` | Independent Hong Kong behavioral observations |

Some top-level threshold fields remain for the legacy detector. With `rapid_move.enabled=true`, the active trade detector uses the `rapid_move` settings instead.

The dashboard also accepts `--port` and `--database`. If you change the collector's database path, pass the same path to the dashboard. Both processes use configuration paths relative to the working directory, so launch them from the repository root.

## Data, privacy, and access

Runtime files are stored under `data/` by default:

| File or directory | Contents |
| --- | --- |
| `quotes.sqlite3` | Received events, alerts, watchlist settings, broker snapshots, and analysis records |
| `quotes.alerts.md` | Human-readable alert history |
| `dashboard-password.txt` | Generated local dashboard password |
| `connection.json`, `us-connection.json` | Collector connection health |
| Trading-calendar and directory JSON files | Cached calendar and symbol metadata |

The dashboard binds to **127.0.0.1 only**. Password protection is optional, and the application is designed for local use. Publishing this source repository does not publish your running dashboard or its database.

The web interface uses bundled assets. Market data queries go to OpenD; Stock Connect reference targets are fetched from Zhitong Finance. Displayed target prices are provider estimates, not guaranteed inclusion prices.

The repository's ignore rules exclude runtime data, virtual environments, passwords, local environment files, logs, database copies, and private-key files. Keep those files out of commits. Back up the SQLite database separately using SQLite's backup facilities or after stopping the application; live databases may also have WAL files.

There is no automatic data retention or rotation policy. Raw event storage grows while the collector runs.

## Useful commands

```sh
# Check available command-line options
.venv/bin/hk-quote --help
.venv/bin/python -m hk_quote.dashboard --help

# Collect for a limited time, then exit
.venv/bin/hk-quote run --seconds 30

# Show saved alerts without starting collection
.venv/bin/hk-quote alerts --limit 100

# Replay saved events; outputs to the terminal without desktop notifications
.venv/bin/hk-quote replay --database data/quotes.sqlite3

# Quickly inspect received order-book depth
.venv/bin/python check_quotes.py --symbols HK.00700 --timeout 5
```

Replay does not write new alerts into the live database. Results depend on the events and boundaries actually recorded; gaps cannot be reconstructed as if they had been observed live.

Daily candlesticks load on demand and use the account's available historical-data quota. Broker polling, optional subscriptions, and manual refreshes also depend on OpenD limits shared with other clients.

## Development

Run the Python tests from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -q
```

Frontend regression scripts are in `tests/*.js`. They can be run with the JavaScriptCore shell on macOS; some use shell helpers such as `load` and `readFile`. See [AGENTS.md](AGENTS.md) for frontend validation requirements.

Key source modules:

| Module | Responsibility |
| --- | --- |
| `main.py`, `us_monitor.py` | Collection, subscriptions, session handling, and notifications |
| `rapid_move.py`, `engine.py` | Joint turnover and price-movement detection |
| `behavior.py`, `behavior_store.py` | Independent behavioral observations and lifecycle storage |
| `broker_archive.py`, `broker_attribution.py`, `broker_periods.py` | Broker snapshots and time-based comparisons |
| `storage.py`, `watchlist.py` | SQLite persistence and monitoring controls |
| `dashboard.py`, `web/` | Local HTTP dashboard and browser interface |

## Futu references

- [Ticker updates](https://openapi.futunn.com/futu-api-doc/quote/update-ticker.html)
- [Order-book updates](https://openapi.futunn.com/futu-api-doc/quote/update-order-book.html)
- [Market data permissions](https://openapi.futunn.com/futu-api-doc/intro/authority.html)

Futu OpenD is a separately installed dependency. This project is an independent application, not an official Futu product.
