# EdgeLab

Quantitative strategy research platform: research → backtest → validate → paper trade → (explicitly gated) live deployment.

Guiding principle: **the platform's job is to kill bad strategies cheaply**, not to make backtests look good. No faked profitability, no same-bar fills, no cost-free trades.

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 15, React 19, TypeScript, Tailwind v4, Framer Motion, Lightweight Charts |
| API | FastAPI (async), Pydantic v2 |
| Engine | Pure Python package (`backend/engine`) — no framework imports |
| DB | PostgreSQL 16 + SQLAlchemy 2 + Alembic |
| Queue | Celery + Redis |
| Deploy | Vercel (frontend) · Railway/Render (api + worker + db + redis) |

## Repo layout

```
backend/
  app/            FastAPI service + Celery workers
    api/v1/       endpoints (health, strategies, backtests)
    models/       SQLAlchemy models (append-only runs for reproducibility)
    schemas/      Pydantic request/response types
    workers/      Celery app + tasks
  engine/         THE core library — framework-free, notebook-friendly
    types.py      Bar, Order, Fill, Position, PortfolioState
    interfaces.py DataFeed / Strategy / CostModel / RiskModel protocols
    backtest.py   event-driven Backtester (Phase 1 build target)
    execution/    cost models (conservative defaults)
    metrics/      Sharpe, Sortino, Calmar, Ulcer, expectancy, ...
    validation/   walk-forward, Monte Carlo (Phase 2)
    risk/         pre-trade limits — same objects guard sim and live
    data/         parquet/provider feeds
frontend/         Next.js app (status page now; dashboard in Phase 4)
docs/             architecture notes
```

## Quick start

```bash
cp .env.example .env          # then edit passwords/keys
make up                       # db + redis + api + worker via docker
make migrate                  # apply alembic migrations
cd frontend && npm i && npm run dev
```

Open http://localhost:3000 — the status page should show api / postgres / redis all green. API docs at http://localhost:8000/docs.

**Auth note (Phase 5):** the research/ops API requires a bearer token in
any deployed environment. For local dev, leave `AUTH_DISABLED=true` in
`.env` (the default) — every request is treated as one fixed local
user, no Supabase project needed. To launch for real testers with their
own isolated logins, see `docs/LAUNCH.md`.

First migration: `make revision m="initial schema"` then `make migrate`.

## Build phases

1. **Engine** — ✅ DONE. Event-driven backtester, FIFO/LIFO lot accounting,
   margin/buying power, market/limit/stop/stop-limit fills with gap and
   partial-fill semantics, full metrics suite. 65 tests, every accounting
   number hand-calculated in test comments; see `docs/ENGINE.md`.
1.5 **Data + SDK (Phase 2)** — ✅ DONE. Canonical OHLCV schema (UTC,
   completion-time stamps, reject-never-repair validation), Parquet store
   with checksums + dataset fingerprints, explicit corporate-action layer,
   provider adapters (CSV/Parquet/Yahoo/Alpaca/Polygon, injected
   transports, env credentials), point-in-time HistoryService, Strategy
   SDK with typed params, tested indicator framework, reproducibility
   manifests. 135 tests total; see `docs/DATA.md`.

1.75 **Validation (Phase 3)** — ✅ DONE. Walk-forward optimization
   (rolling/expanding/overlapping windows), structurally protected final
   holdout, grid/random/Latin-Hypercube search, sensitivity analysis
   (neighbor consistency, stability regions, robustness scores that
   prefer plateaus), seeded Monte Carlo (reshuffle/bootstrap/skip +
   cost-perturbation and delayed-execution engine re-runs), regime
   attribution, overfitting warnings, ranked strategy comparison, and
   research reports that separate measured statistics from
   interpretation. 196 tests; see `docs/VALIDATION.md`.

1.9 **Research terminal (Phase 4)** — ✅ DONE. Filesystem experiment
   registry with search (free text + metric expressions), a research
   pipeline that runs the full validation suite per experiment (holdout
   reserved first, walk-forward selection, sensitivity grid, Monte Carlo
   fan + probability of ruin, regimes, warnings, one-shot holdout
   evaluation), one-click PDF reports with the disclaimer on every page,
   and a Next.js terminal: dashboard, experiment detail (fold timeline
   with per-trade inspection, hover parameter heatmaps, MC fan),
   comparison, dataset explorer, reports, history, notes. 213 tests; see
   `docs/TERMINAL.md`.

1.95 **Operations layer (Phase 5)** — ✅ DONE. Immutable, hash-identified
   deployments with a gated lifecycle (proposed → paper → live →
   review/retired); a normalized live market engine (replay/simulated-
   live/broker feeds); a strategy runtime that runs the exact validated
   SDK code and only ever proposes signal candidates; an 11-check risk
   engine (kill switch, hours, data quality, duplicates, sizing, spread,
   liquidity, position/exposure limits, daily loss, buying power); a
   paper broker with realistic spread/slippage/partial-fill/commission
   modeling sharing one live loop with paper and (future) live trading —
   proven both by exact signal parity with the Phase 1 backtester and by
   fill-for-fill crash recovery; deployment health vs. research Monte
   Carlo bands; edge drift detection (six triggers, evidence-only, never
   auto-disables); a pattern library + descriptive (not predictive)
   similarity engine; a rule-based automated research assistant and
   nightly batch runner with morning reports; six new terminal pages
   (Deployments, Live Monitoring, Edge Health, Research Queue, Pattern
   Library, Morning Brief); and Supabase-backed auth with per-user data
   isolation for multi-tenant testing (every deployment, experiment, and
   pattern is namespaced by user id; verified by a dedicated isolation
   test). 291 tests total; see `docs/OPERATIONS.md` for the architecture
   and `docs/LAUNCH.md` to actually get a small group of testers onto
   their own accounts.

2. **API depth** — result artifacts (equity curves, trade logs), progress streaming over Redis.
3. **Frontend polish** — richer charting (Lightweight Charts), keyboard navigation.
4. **Live execution** — a real broker adapter (Alpaca or similar) implementing the `Broker` protocol Phase 5 defines, wired into the same `LiveLoop`. Stays disabled until explicitly enabled per account.

## Non-negotiable engine rules

1. Signals on bar *t* fill at bar *t+1* open. Never same-bar.
2. Every fill passes through a cost model.
3. Equity is marked to market every bar.
4. Deterministic runs; all randomness seeded.
5. Completed backtest runs are immutable rows.
