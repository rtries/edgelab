"use client";
/** Experiment registry: every run, searchable. Free text, exact facets,
 * and metric expressions ("sharpe>1.5") straight through to the API. */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, fmt, type ExperimentSummary } from "@/lib/api";
import { ConfidenceStamp, DataTable, ErrorBox, Loading, Panel, Tag } from "@/components/ui";

const inputCls =
  "rounded border border-ink-800 bg-ink-950 px-2 py-1 text-sm figure placeholder:text-ink-400 focus:border-amber-signal focus:outline-none";

export default function ExperimentsPage() {
  const [rows, setRows] = useState<ExperimentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [filters, setFilters] = useState("");
  const [strategy, setStrategy] = useState("");
  const [tag, setTag] = useState("");
  const [engineVersion, setEngineVersion] = useState("");
  const [confidence, setConfidence] = useState("");

  const search = useCallback(() => {
    setError(null);
    api
      .experiments({
        text,
        filters,
        strategy,
        tag,
        engine_version: engineVersion,
        confidence,
      })
      .then(setRows)
      .catch((e) => setError(String(e)));
  }, [text, filters, strategy, tag, engineVersion, confidence]);

  useEffect(() => {
    search();
  }, [search]);

  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Experiment registry</h1>
      <Panel title="Search — never lose research">
        <div className="flex flex-wrap items-center gap-2">
          <input className={inputCls} placeholder="free text (id, strategy, symbol, tag)" value={text} onChange={(e) => setText(e.target.value)} size={30} />
          <input className={inputCls} placeholder="filters e.g. sharpe>1.5,n_trades>30" value={filters} onChange={(e) => setFilters(e.target.value)} size={28} />
          <input className={inputCls} placeholder="strategy" value={strategy} onChange={(e) => setStrategy(e.target.value)} size={14} />
          <input className={inputCls} placeholder="tag" value={tag} onChange={(e) => setTag(e.target.value)} size={10} />
          <input className={inputCls} placeholder="engine version" value={engineVersion} onChange={(e) => setEngineVersion(e.target.value)} size={12} />
          <select className={inputCls} value={confidence} onChange={(e) => setConfidence(e.target.value)}>
            <option value="">any confidence</option>
            {["strong", "moderate", "weak", "insufficient"].map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <p className="mt-2 text-[10px] text-ink-400">
          Filter metrics: sharpe, sortino, max_drawdown, profit_factor, expectancy, win_rate,
          n_trades, exposure, val_sharpe_mean, mc_sharpe_lower, final_sharpe, n_warnings.
        </p>
      </Panel>

      {error && <ErrorBox error={error} />}
      {!rows && !error && <Loading label="searching" />}
      {rows && (
        <Panel title={`${rows.length} result${rows.length === 1 ? "" : "s"}`}>
          <DataTable
            columns={["id", "created", "strategy", "symbols", "params", "dev sharpe", "val mean", "mc lower", "holdout", "confidence", "tags"]}
            rows={rows.map((e) => [
              <Link key="id" href={`/experiments/${e.id}`} className="text-amber-signal hover:underline">{e.id}</Link>,
              fmt.date(e.created_at),
              e.strategy,
              e.symbols.join(" "),
              <span key="p" className="text-xs text-ink-400">{Object.entries(e.selected_params).map(([k, v]) => `${k}=${v}`).join(" ")}</span>,
              <span key="s" className={Number(e.metrics.sharpe) >= 0 ? "text-gain" : "text-loss"}>{fmt.signed(e.metrics.sharpe)}</span>,
              fmt.signed(e.val_sharpe_mean),
              fmt.signed(e.mc_sharpe_lower),
              <span key="h" className={Number(e.final_sharpe) >= 0 ? "text-gain" : "text-loss"}>{fmt.signed(e.final_sharpe)}</span>,
              <ConfidenceStamp key="c" level={e.confidence} size="sm" />,
              <span key="t" className="flex gap-1">{e.tags.map((t) => <Tag key={t}>{t}</Tag>)}</span>,
            ])}
          />
        </Panel>
      )}
    </div>
  );
}
