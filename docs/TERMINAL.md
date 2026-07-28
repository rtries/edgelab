# Research terminal (Phase 4)

The workspace layer: a Next.js terminal over a filesystem-backed research
API. Zero external services needed for research — Postgres/Redis/Celery
remain reserved for live workloads in later phases.

## Run it

```bash
# 1) seed synthetic data + four experiments (from backend/)
python scripts/seed_research.py

# 2) research API (from backend/)
EDGELAB_RESEARCH_ROOT=$PWD/research_data \
EDGELAB_DATA_ROOT=$PWD/data/store \
python -m uvicorn app.main:app --port 8000

# 3) terminal (from frontend/)
npm install && npm run dev        # http://localhost:3000
# point at a remote API with NEXT_PUBLIC_API_URL
```

## What each view is

- **Dashboard** — the research program at a glance: experiment counts by
  confidence, recent runs, datasets, latest notes.
- **Experiments** — the registry. Free-text search plus metric filter
  expressions (`sharpe>1.5,n_trades>30`), strategy/tag/engine-version/
  confidence facets. Nothing is ever lost; re-runs are new entries.
- **Experiment detail** — six tabs, all reading the persisted experiment
  JSON (the UI computes nothing):
  *Overview* (development equity/drawdown/monthly/trade distribution/
  exposure + the single holdout evaluation, clearly separated),
  *Walk Forward* (fold timeline — click any fold, inspect its validation
  equity and every trade), *Parameters* (hover heatmap: sharpe, drawdown,
  profit factor, win rate per cell; robustness/consistency/plateau),
  *Monte Carlo* (fan of reshuffled paths with 5–95% bands, best/worst,
  probability-of-ruin table, CI tables per method, delay sweep),
  *Regimes*, *Report* (markdown + one-click PDF).
- **Compare** — overlay any experiments: normalized equity, side-by-side
  validation/MC/holdout table, monthly grids, trade distributions.
- **Optimization / Walk Forward / Monte Carlo** — cross-experiment
  indexes that deep-link into the relevant detail tab.
- **Datasets** — fingerprint, sources, adjustment policy, calendar,
  coverage, missing sessions, integrity verification, corporate-action
  status, price preview.
- **Reports** — every experiment's PDF (exec summary with confidence
  stamp, methodology, charts, warnings; disclaimer on every page).
- **History** — chronological trail of every run.
- **Notes** — write down what didn't work; it's half the value.
- **Portfolio** — deliberately empty until Phase 5 paper trading; the
  page says why instead of pretending.

## Design decisions

- **Experiment JSON is the unit of record.** The pipeline measures once,
  under a seed; every view renders those stored numbers. No client-side
  statistics, no drift between screen and report.
- **Filesystem store.** `research_data/` holds `experiments/*.json`,
  `index.json`, `notes/`, and the optimization-count registry. Portable,
  diffable, service-free.
- **Confidence stamp everywhere.** An experiment never appears without
  its verdict. "Strong" is defined in code as "the evidence gathered here
  did not kill the strategy" — and the seeded demo runs honestly stamp
  *insufficient* on random synthetic data.
- **Charts are hand-rolled SVG.** Deterministic, dependency-free,
  themable with the terminal tokens; the fold timeline (train ink /
  validate amber / holdout red, "evaluated once") is the signature.

## Limitations

- Experiment launches run synchronously in the API process — fine for
  local research on stored data; Celery offload is wired for later.
- The registry index is a JSON file: perfect up to thousands of runs,
  not a database.
- No auth; the terminal is a local instrument.
