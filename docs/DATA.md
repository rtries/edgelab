# Data infrastructure (Phase 2)

## Canonical schema
Columns: `symbol, ts, open, high, low, close, volume, timeframe, source`.
`ts` is tz-aware UTC and means the bar's **completion time** (candle close).
Daily bars complete at the calendar's session close (default 21:00 UTC).
This one convention makes multi-timeframe lookahead prevention structural:
a bar is usable exactly when `now >= ts`, so a daily candle simply does not
exist mid-session.

`normalize()` may transform (tz conversion, sorting, column shaping);
`validate()` never mutates — corrupted data (OHLC violations, duplicates,
non-positive prices, negative volume) is **rejected, never repaired**.
Calendar completeness checks are configurable: `on_missing = ignore |
report | error`, with holidays and early closes handled by
`WeekdayCalendar`.

## Store
`ParquetStore` at `data/store/`: `{timeframe}/{symbol}.parquet` +
`manifest.json` with row counts, ranges, sources, and sha256 checksums
computed over a canonical serialization of the *values* — so identical
data has an identical checksum no matter how it arrived (CSV vs Parquet,
tested). Writes are incremental merges: identical rows are idempotent;
same-timestamp different-values raises `DataIntegrityError`. The store
holds **raw prices only**; `verify()` detects external tampering.

## Adjustments
Explicit layer, applied at load time: `raw`, `split`, `total_return`
(CRSP-style proportional dividend method on split-adjusted closes).
Double adjustment is refused; feeds and the history service refuse mixed
modes; the mode is recorded in every run manifest.

## Providers
`CSVProvider`, `ParquetProvider`, `YahooProvider`, `AlpacaProvider`,
`PolygonProvider` — all return canonical raw frames. Network adapters take
an injected `transport` callable (tests use fixtures, never the network),
read credentials from `ALPACA_API_KEY`/`ALPACA_API_SECRET`/
`POLYGON_API_KEY`, and re-stamp provider timestamps to completion time
(daily → session close; Alpaca/Polygon intraday start-stamps → +interval).

## Reproducibility
`run_research_backtest()` fingerprints the exact dataset slice
(per-symbol checksums → sha256), resolves typed params, wraps the strategy
in the SDK adapter, runs the frozen Phase 1 engine, and attaches a
manifest: strategy name + source-code hash, params, dataset fingerprint +
snapshot, symbols, timeframe, dates, adjustment mode, cost model, engine
version, account config, run timestamp. Same inputs ⇒ identical results
(tested); only `run_at` may differ.

## Exact commands
```bash
cd backend

# One-shot demo: synthesize CSV -> import -> verify -> backtest twice
python scripts/demo_backtest.py

# Importing your own CSV (columns: ts,open,high,low,close,volume)
python - << 'PY'
import sys; sys.path.insert(0, ".")
from datetime import date
from engine.data.providers.local import CSVProvider
from engine.data.schema_types import Timeframe
from engine.data.store import ParquetStore

frame = CSVProvider("data/csv").fetch("DEMO", Timeframe.D1, date(2024,1,1), date(2024,12,31))
store = ParquetStore("data/store")
print(store.write(frame))
store.verify("DEMO", Timeframe.D1)
PY

# Running a backtest against the store
python - << 'PY'
import sys; sys.path.insert(0, ".")
from datetime import datetime, UTC
from engine.data.schema_types import AdjustmentMode, Timeframe
from engine.data.store import ParquetStore
from engine.execution.costs import SimpleCostModel
from engine.run import run_research_backtest
from engine.strategies.examples import MACrossover

result = run_research_backtest(
    store=ParquetStore("data/store"), strategy=MACrossover(),
    symbols=["DEMO"], timeframe=Timeframe.D1,
    start=datetime(2024,1,1,tzinfo=UTC), end=datetime(2024,12,31,tzinfo=UTC),
    params={"fast": 5, "slow": 15}, cost_model=SimpleCostModel(),
    adjustment_mode=AdjustmentMode.RAW, initial_cash=100_000)
print(result.metrics); print(result.manifest["dataset_fingerprint"])
PY

# Full test suite
python -m pytest tests -q
```

## Known limitations (deliberate)
- `WeekdayCalendar` uses fixed UTC session times: US DST shifts and true
  exchange holiday calendars need a real calendar backend (same interface).
- DAY orders expire on calendar-date change, not session close (Phase 1).
- Corporate actions must be supplied by the caller; no provider fetches
  splits/dividends yet.
- Yahoo daily bars use raw quotes; intraday Yahoo timestamps are passed
  through as given (verify per exchange before trusting).
- One execution timeframe per run; higher timeframes are context via
  `extra_history`, not execution streams.
