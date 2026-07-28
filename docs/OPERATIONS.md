# Operations layer (Phase 5)

Turns EdgeLab from a research tool that judges strategies into a system
that also runs, watches, and retires them — without ever pretending it
can predict what a strategy will do next.

**EdgeLab cannot predict future prices.** Everything in this layer
estimates whether *current* market conditions resemble the conditions a
strategy was *previously validated on*, and continuously re-checks that
estimate. A deployment is a hypothesis under permanent test, not a
belief the system holds. When the evidence turns, the system says so —
it never decides to stop trading on your behalf.

## The lifecycle

```
Research → Validation → Deployment → Paper Trading → Live Monitoring
                                                    ↘ Edge Monitoring → Retirement
```

Concretely: an `Experiment` (Phase 4) that reaches `moderate` or
`strong` confidence can become a `Deployment` (`ops/deployments.py`).
Deployments are **immutable** — the id is a hash of the entire config
block (strategy, params, risk policy, engine version, dataset
fingerprint, confidence, warnings). Change anything and you get a new
id, i.e. a new deployment; the old one's record is untouched. Nothing
overwrites history.

Status moves through a fixed graph, enforced server-side, never
client-side:

```
proposed ──► rejected
proposed ──► paper     [requires confidence ∈ {moderate, strong}]
paper    ──► review | retired
paper    ──► live      [requires confidence == strong AND paper evidence:
                         ≥ 20 trades, health == 'healthy']
live     ──► review | retired
review   ──► paper | live | retired
```

Every transition is recorded with a timestamp, a reason, and — for
`live` — the evidence that justified it. `flag_for_review()` (called
automatically by drift detection) only ever sets a flag and appends
evidence; **it never changes `status`**. Moving a flagged deployment out
of trading is always a separate, deliberate, recorded transition.

## The paper == live guarantee

This is the central engineering claim of Phase 5, and it's structural,
not a promise: `ops/loop.py`'s `LiveLoop` is the *only* code that runs a
deployment, whether the feed is historical replay, a simulated live
feed, or a real broker feed. Per event:

1. `broker.on_event` — apply fills for orders accepted on earlier events
2. `ledger.mark` — mark the position at the new close
3. `runtime.on_bar` — ask the strategy: does the current market satisfy
   you? (`ops/runtime.py`, running the *exact* SDK-adapted strategy code
   Phase 4 validated — same class, same resolved params)
4. pattern feature snapshot per candidate (`ops/patterns.py`)
5. `risk.evaluate` — the candidate through the full risk chain
   (`ops/risk.py`)
6. `broker.submit` — the *only* path from a candidate to a working order

Paper and live share every one of these; only the `Broker` and `Feed`
adapters differ (a live broker adapter, credentials, and reconnection
handling are Phase 6 — see Limitations). Event logs use one shared JSON
schema (`stream`, `kind`, `ts`, `received_at`, `deployment_id`, ...), so
paper and live logs are diffable by construction, and `PaperBroker`
already models what live execution will face: bid/ask crossing,
modeled slippage, participation-capped partial fills, per-share
commissions (the same `SimpleCostModel` research uses), and rejections
for closed markets or insufficient buying power.

**This is proven, not just designed.** `test_runtime_signal_parity_with_backtester`
runs the identical bars through the live loop and through Phase 1's
`Backtester` and asserts the two order streams — timestamp, symbol,
side — are exactly equal. `test_crash_recovery_equals_uninterrupted_run`
kills a loop mid-stream, checkpoints, resumes in a brand-new `LiveLoop`
object, and asserts the resumed run is fill-for-fill identical to an
uninterrupted reference run — including in-flight working orders, which
the checkpoint carries via `PaperBroker.serialize()/restore()`.

## Every candidate order passes through 11 checks, in order

`ops/risk.py`, one fixed chain: **emergency stop → market hours → data
quality → duplicate protection → sizing → spread → liquidity → position
limit → gross exposure → daily loss limit → buying power.** A
`SignalCandidate` from the strategy is only ever the strategy's
*opinion*; the risk chain decides whether it becomes an order, and every
rejection is logged with the exact check and evidence that stopped it.
Exit signals (`is_closing=True`) bypass the entry-only gates (spread,
liquidity, position/exposure limits, daily loss) so a position is never
trapped by market conditions worsening after entry — but never bypass
the kill switch, market hours, data quality, or buying power.

Sizing (`RiskPolicy.sizing_mode`) supports `pct_equity` (floor of
equity × fraction ÷ price) and `fixed_qty`. All other policy fields —
position/exposure caps, daily loss limit, spread/liquidity floors,
duplicate cooldown, short permission — are per-deployment and immutable
along with everything else in the config block.

## Deployment health and edge drift

`ops/health.py` compares live-observed metrics (win rate, profit
factor, expectancy, Sharpe, drawdown, trade frequency, holding time,
realized slippage) against the *research* point estimate **and** its
Monte Carlo confidence band (`ops/health.py: expectation_from_experiment`
reads the reshuffle/bootstrap quantiles Phase 3 already computed).
Every row states its sample size; small samples are shown as small
samples, not silently trusted.

`ops/drift.py` runs six deterministic, documented triggers over that
comparison:

| trigger | fires when |
|---|---|
| `slippage_excess` | realized slippage > 2× the modeled slippage |
| `frequency_shift` | trade frequency ratio outside [0.5×, 2×] of research |
| `distribution_change` | KS statistic between research and live trade P&Ls > 0.5 (needs ≥ 8 trades each side) |
| `win_rate_collapse` | observed win rate below research win rate − 2σ (binomial) |
| `drawdown_breach` (**critical**) | observed drawdown deeper than the research MC q2.5 bad case |
| `regime_shift` | current market regime had ≤ 0 research Sharpe |

Trigger count maps to a status: 0 → `healthy`, 1 → `weakening`, 2 →
`unstable`, ≥ 3 or any critical trigger → `retire_recommended`. **The
system never acts on this status.** It calls `flag_for_review()`, which
sets `review_required=True` and appends the evidence — the deployment
keeps trading exactly as configured until a human (or an explicit API
call) makes the transition.

## Pattern library and similarity

Every accepted signal is snapshotted (`ops/patterns.py`): volatility and
trend regime (Phase 3's classifier on trailing closes), 14-bar ATR%,
20-bar trailing annualized vol, gap vs. previous close, relative volume,
time of day, spread, dollar volume, and sector (via an injectable map).
Two fields the mission brief asked for — **breadth** and true
**VWAP relationship** — are recorded as `null` rather than faked,
because they require a tracked universe and intraday data respectively,
neither of which single-symbol daily bars provide (see Limitations).
Outcomes attach when the round trip closes: net/gross P&L, win/loss,
holding time.

`ops/similarity.py` z-scores the numeric features actually present
across the library, runs Euclidean k-NN, and returns neighbors plus an
outcome distribution (win rate, mean/median P&L, dispersion, sample
size). Every result carries a fixed framing string — **"descriptive,
not predictive"** — because a five-neighbor win rate is a fact about a
small historical sample, not a forecast, and nothing downstream should
be able to present it as one.

## Continuous research

`ops/assistant.py` is a **rule-based** hypothesis generator: strategy
templates × symbols × parameter grids, enumerated deterministically
under a seed, with rationale text built from measured dataset
statistics (volatility, total return, bar count) — never a claim about
future performance. Hypotheses are checked against the experiment
registry for novelty before running. Every surviving hypothesis goes
through the **exact same Phase 4 pipeline** a human-launched experiment
uses — holdout enforced, no shortcuts — then classified honestly:

- `passed` — confidence reached moderate or strong
- `needs_more_data` — blocked specifically by the `few_trades` critical warning
- `rejected` — anything else that didn't clear the bar

`ops/nightly.py` runs a batch, tallies the four outcomes, and writes a
morning report (JSON + Markdown) that also folds in deployment health
alerts. One bad hypothesis (a data error, an unsupported param grid)
never aborts the batch — it's caught, recorded in an `errors` list, and
the rest of the batch continues. **An LLM can replace the hypothesis
generator in Phase 6 without changing anything downstream** — a
hypothesis is a structured proposal, and validation remains the actual
gate.

## Terminal extensions

Same visual language and component kit as Phase 4 (`Panel`, `Stat`,
`ConfidenceStamp`, `DataTable`, `Tabs`). New pages: **Deployments**
(registry + detail with Config/Health/Drift/Paper tabs and lifecycle
transition buttons that call the gated API — no client-side bypass is
possible), **Live Monitoring** (the emergency-stop control plus a view
of active deployments), **Edge Health** (a drift board across every
paper/live deployment), **Research Queue** (pending hypotheses, a
manual nightly trigger, recent reports), **Pattern Library** (search +
similarity lookup, always shown with the descriptive-not-predictive
note), and **Morning Brief** (the one-stop aggregate: deployment
alerts, last night's research, newly validated ideas, retirement
recommendations).

## Assumptions, stated plainly

- **Paper fill modeling** uses the bar's open ± half the policy's
  modeled spread (or a live quote if one was seen), plus a fixed
  slippage-bps adverse move, capped by a participation-of-volume limit
  for partial fills. This is a model, not a guarantee real fills will
  match — it uses the same `SimpleCostModel` research validation
  assumed, so paper results are at least *comparable* to backtest
  results by construction.
- **Daily loss limit** resets on UTC calendar-date rollover of the
  event stream, using the WeekdayCalendar's session boundaries.
- **Breadth and VWAP-relative features** are `null` on the current
  single-symbol daily-bar setup (see above) rather than approximated.
- **KS-based distribution drift** needs ≥ 8 trades on both the research
  and live sides before it evaluates at all; below that it stays
  silent rather than firing on noise.
- **The 2×/0.5×, 2σ, KS 0.5, and MC-band thresholds in `ops/drift.py`
  are pinned heuristics**, documented in the module docstring, not
  statistically derived optimal cutoffs.
- **Regime shift detection** depends on the experiment's regime table
  having a matching regime label passed by the caller; if none is
  supplied, that trigger is silent.

## Remaining limitations

- No live broker adapter with real credentials, order acknowledgment,
  or reconnection/backoff logic — `AlpacaFeed` normalizes messages from
  an injected `Transport`, but a production websocket/HTTP transport,
  auth, and a live-side `Broker` implementation are not built.
- No cancel support (`_RuntimeContext.cancel` always returns `False`) —
  strategies can submit but not withdraw a working order.
- No true intraday data path (VWAP, breadth) — the store and loop
  support any timeframe structurally, but the shipped dataset and
  examples are daily.
- Nightly research runs synchronously in-process; a real deployment
  would want this on a scheduler (cron/Celery) with alerting on
  batch failure, not just per-hypothesis error capture.
- Sector mapping for pattern features is an injectable dict with no
  default data source.
- No authentication/authorization on the ops API — anyone who can
  reach it can create deployments, toggle the emergency stop, or run
  research batches. This is a local research/paper system, not a
  hardened multi-tenant service.

## Recommendations for Phase 6

1. **Live broker adapter** (Alpaca or similar): real transport,
   auth, reconnection with gap detection against the last processed
   event, and a `Broker` implementation that submits real orders while
   reusing every other piece of the loop unchanged.
2. **Order cancellation** end-to-end (context → runtime → broker →
   log), needed once real market conditions can outrun the next-bar
   discipline strategies were validated under.
3. **LLM-assisted hypothesis generation** as a second `ops/assistant.py`
   generator, swappable behind the same `Hypothesis` interface —
   validation remains the gate either way.
4. **Intraday data + true VWAP/breadth features** once a market-data
   provider is wired in, removing the two `null` pattern fields.
5. **Scheduled nightly runs** with batch-level alerting (not just the
   per-hypothesis error list) and a retry policy.
6. **Authn/authz** on the ops API before any deployment beyond a
   single trusted operator's machine.
7. **Multi-strategy portfolio-level risk** (today's exposure/position
   caps are per-deployment; a shared account across many live
   deployments needs an account-level view).
