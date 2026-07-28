# Statistical validation (Phase 3)

Purpose: determine whether a strategy shows evidence of a genuine edge
rather than historical luck. Everything here consumes the frozen Phase 1/2
pipeline through `BacktestResult` and a `runner(params, start, end)`
callable; no engine semantics were touched.

## Windowing and out-of-sample discipline
`WindowSpec(train_size, val_size, step, expanding)` generates folds over
the dataset's actual bar index (counts, not calendar math). `step <
val_size` gives overlapping validation; `expanding=True` grows train from
bar 0. Per fold, candidates are scored on TRAIN only; the winner is then
run once on VALIDATION. `reserve_final_test()` splits off the tail
holdout **before** anything else and returns a `FinalTestSet` guard whose
`evaluate()` works exactly once — optimizing on the holdout is an API
impossibility, not a convention.

## Search
Grid (full cartesian over `Param` min/max/step grids), random (seeded,
snapped to the grid), Latin Hypercube (seeded, one sample per stratum per
dimension — verified by a stratification test). Ties on the objective
break by parameter tuple; NaN objectives never win.

## Sensitivity — prefer plateaus over spikes
On a regular grid: `neighbor_consistency` = mean objective of the
optimum's Manhattan neighbors / peak (clipped to [0,1], 0 for non-positive
peaks); `plateau_fraction` = size of the top-quartile connected component
containing the optimum / all combos; `robustness_score` =
sqrt(consistency × plateau_fraction) — the geometric mean demands BOTH a
supportive neighborhood and a broad region. Hand-fixtured on constructed
spike vs plateau surfaces (0.236 vs 0.943). `heatmap(x, y)` pivots mean
objective over the remaining parameters.

## Monte Carlo
Trade-level resampling (reshuffle / bootstrap / random skip) rebuilds
equity **additively** (initial + cumulative P&L) — a stated approximation
that stays faithful to the recorded trades and hides no model. Sharpe on
synthetic paths uses per-trade returns annualized by trades/year; CAGR
uses the original span. Execution perturbations re-run the *full engine*:
seeded slippage/commission multipliers via `dataclasses.replace` on the
cost model, and execution delay via `DelayedStrategy`, a strategy-layer
wrapper that buffers submissions per symbol (delay 0 proven behaviorally
identical to unwrapped). Confidence intervals: `np.quantile` (linear) at
0.025/0.5/0.975 by default; infinities dropped. Every random component
takes an explicit seed; identical seeds ⇒ identical outputs (tested).

## Regimes
Volatility (rolling std, full-sample **median split** — in-sample and
descriptive, explicitly not a tradable signal), trend (trailing return vs
±threshold → bull/bear/sideways), trending = bull|bear. Warm-up bars are
"undefined" and excluded. `regime_metrics` joins strategy per-bar returns
to same-timestamp labels: n_bars, total/mean/std return, annualized
Sharpe per regime.

## Overfitting warnings (heuristics with pinned thresholds)
narrow_peak (consistency < 0.5, critical < 0.25); train_val_divergence
(validation ≤ 0 while train > 0 is critical; retaining < 50% warns);
few_trades (< 30, critical < 10); excessive_complexity (combos searched >
trades); unstable_surface (fold-to-fold chosen-param dispersion > 0.25 of
the search range); repeated_optimization (`OptimizationRegistry` counts
runs per dataset-fingerprint × strategy-hash, warns past 3, optional JSON
persistence). Absence of warnings is never treated as evidence of edge.

## Comparison
Direction-aware ranks (higher-better: sharpe, sortino, calmar, PF,
expectancy, MC sharpe lower CI; lower-better: ulcer, validation
consistency = std of fold objectives; |max drawdown| closer to zero
better). `overall_rank` = mean rank; n_trades and exposure are context
columns, deliberately unranked.

## Report
`build_report()` produces a structure with a hard wall between MEASURED
(numbers by pinned definitions) and INTERPRETATION (warnings + a
deterministic confidence rubric: insufficient / weak / moderate / strong;
"strong" requires ≥ 75% positive folds, MC lower CI > 0, and zero
warnings — and is defined in-code as "the evidence gathered here did not
kill the strategy"). Every report embeds the disclaimer; markdown
rendering is tested for it. Reports are reproducible except
`generated_at`.

## Known limitations
- Thresholds are honest heuristics, not statistical tests; no deflated
  Sharpe ratio, White's Reality Check, or SPA test yet.
- Trade-level MC paths are additive, not compounded position sizing.
- Regime labels are in-sample (median split) — attribution only.
- Single-objective optimization; no multi-objective fronts.
- The registry only counts optimizations routed through it.
