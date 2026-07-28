"use client";
/** Pattern Library — search executed setups, or describe a market
 * situation and find historical neighbors. Similarity results are
 * always shown with their framing note: descriptive, not predictive. */
import { useState } from "react";
import { api, fmt, type PatternRecord, type SimilarityResult } from "@/lib/api";
import { DataTable, ErrorBox, Loading, Panel } from "@/components/ui";

const inputCls =
  "rounded border border-ink-800 bg-ink-950 px-2 py-1 text-sm figure placeholder:text-ink-400 focus:border-amber-signal focus:outline-none";

function outcomeCell(r: PatternRecord) {
  if (!r.outcome) return <span className="text-ink-400">open</span>;
  return (
    <span className={r.outcome.win ? "text-gain" : "text-loss"}>
      {fmt.signed(r.outcome.net_pnl)}
    </span>
  );
}

export default function PatternLibraryPage() {
  const [strategy, setStrategy] = useState("");
  const [symbol, setSymbol] = useState("");
  const [volRegime, setVolRegime] = useState("");
  const [outcome, setOutcome] = useState("");
  const [results, setResults] = useState<PatternRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [atrPct, setAtrPct] = useState("");
  const [rvol, setRvol] = useState("");
  const [similarity, setSimilarity] = useState<SimilarityResult | null>(null);
  const [simError, setSimError] = useState<string | null>(null);

  function search() {
    setError(null);
    api
      .patterns({ strategy, symbol, vol_regime: volRegime, outcome })
      .then(setResults)
      .catch((e) => setError(String(e)));
  }

  function findSimilar() {
    setSimError(null);
    const features: Record<string, number> = {};
    if (atrPct) features.atr_pct = Number(atrPct);
    if (rvol) features.rvol = Number(rvol);
    if (Object.keys(features).length === 0) {
      setSimError("enter at least one feature value");
      return;
    }
    api.similarPatterns(features, 10).then(setSimilarity).catch((e) => setSimError(String(e)));
  }

  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Pattern Library</h1>
      <p className="text-xs text-ink-400">
        Every executed setup, snapshotted with its market context and — once
        the position closes — its outcome. A historical database, not a
        signal source.
      </p>

      <Panel title="Search">
        <div className="flex flex-wrap items-center gap-2">
          <input className={inputCls} placeholder="strategy" value={strategy} onChange={(e) => setStrategy(e.target.value)} size={16} />
          <input className={inputCls} placeholder="symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} size={10} />
          <select className={inputCls} value={volRegime} onChange={(e) => setVolRegime(e.target.value)}>
            <option value="">any vol regime</option>
            <option value="low">low</option>
            <option value="normal">normal</option>
            <option value="high">high</option>
          </select>
          <select className={inputCls} value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="">any outcome</option>
            <option value="win">win</option>
            <option value="loss">loss</option>
            <option value="open">open</option>
          </select>
          <button
            onClick={search}
            className="rounded border border-ink-700 px-3 py-1 text-xs uppercase tracking-widest text-ink-100 hover:border-amber-signal hover:text-amber-signal"
          >
            Search
          </button>
        </div>
      </Panel>

      {error && <ErrorBox error={error} />}
      {results && (
        <Panel title={`${results.length} record${results.length === 1 ? "" : "s"}`}>
          <DataTable
            columns={["ts", "strategy", "symbol", "side", "vol regime", "trend regime", "outcome"]}
            rows={results.map((r) => [
              fmt.time(r.ts),
              r.strategy,
              r.symbol,
              r.side,
              String(r.features.vol_regime ?? "—"),
              String(r.features.trend_regime ?? "—"),
              outcomeCell(r),
            ])}
          />
        </Panel>
      )}

      <Panel title="Find similar historical setups">
        <div className="flex flex-wrap items-center gap-2">
          <input className={inputCls} placeholder="atr_pct e.g. 0.015" value={atrPct} onChange={(e) => setAtrPct(e.target.value)} size={14} />
          <input className={inputCls} placeholder="rvol e.g. 1.5" value={rvol} onChange={(e) => setRvol(e.target.value)} size={10} />
          <button
            onClick={findSimilar}
            className="rounded border border-amber-signal px-3 py-1 text-xs uppercase tracking-widest text-amber-signal hover:bg-amber-signal/10"
          >
            Find neighbors
          </button>
        </div>
        {simError && <p className="mt-2 text-xs text-loss">{simError}</p>}
        {similarity && (
          <div className="mt-3 space-y-3">
            <p className="rounded border border-amber-signal/40 bg-amber-signal/5 p-2 text-xs text-amber-signal">
              {similarity.note}
            </p>
            <div className="flex flex-wrap gap-6 text-sm">
              <span>n <span className="figure text-ink-100">{similarity.outcome_distribution.n}</span></span>
              <span>resolved <span className="figure text-ink-100">{similarity.outcome_distribution.n_resolved ?? 0}</span></span>
              <span>win rate <span className="figure text-ink-100">{fmt.pct(similarity.outcome_distribution.win_rate ?? null)}</span></span>
              <span>mean pnl <span className="figure text-ink-100">{fmt.signed(similarity.outcome_distribution.mean_pnl ?? null)}</span></span>
              <span>pnl std <span className="figure text-ink-100">{fmt.signed(similarity.outcome_distribution.pnl_std ?? null)}</span></span>
            </div>
            <DataTable
              columns={["distance", "symbol", "ts", "outcome"]}
              rows={similarity.neighbors.map((n) => [
                fmt.num(n.distance, 3),
                n.symbol,
                fmt.time(n.ts),
                outcomeCell(n),
              ])}
            />
          </div>
        )}
      </Panel>
    </div>
  );
}
