"use client";
/** Research Queue — hypotheses waiting to be tested, plus a manual
 * trigger for a nightly batch and a feed of recent reports. The
 * assistant is rule-based today (templates × symbols × grids); the
 * rationale text is generated from measured dataset stats, not a claim
 * about the future. */
import { useEffect, useState } from "react";
import { api, fmt, type NightlyResult } from "@/lib/api";
import { DataTable, ErrorBox, Loading, Panel, Tag } from "@/components/ui";

const inputCls =
  "rounded border border-ink-800 bg-ink-950 px-2 py-1 text-sm figure placeholder:text-ink-400 focus:border-amber-signal focus:outline-none";

const CLASS_TONE: Record<string, string> = {
  passed: "text-gain",
  needs_more_data: "text-amber-signal",
  rejected: "text-ink-400",
};

export default function ResearchQueuePage() {
  const [symbols, setSymbols] = useState("DEMO");
  const [budget, setBudget] = useState(10);
  const [queue, setQueue] = useState<Record<string, unknown>[] | null>(null);
  const [reports, setReports] = useState<{ date: string; tallies: NightlyResult["tallies"] }[] | null>(null);
  const [lastRun, setLastRun] = useState<NightlyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const symbolList = symbols.split(",").map((s) => s.trim()).filter(Boolean);

  const reload = () => {
    api.researchQueue(symbolList.length ? symbolList : undefined).then(setQueue).catch((e) => setError(String(e)));
    api.reports().then(setReports).catch(() => setReports([]));
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runNightly() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.triggerNightly(symbolList, budget);
      setLastRun(result);
      reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Research Queue</h1>
      <p className="text-xs text-ink-400">
        Every hypothesis runs through the identical validation pipeline a
        human-launched experiment does — holdout enforced, no shortcuts.
        Most ideas here should be rejected; that is the pipeline working.
      </p>

      <Panel title="Run a batch">
        <div className="flex flex-wrap items-center gap-2">
          <input className={inputCls} placeholder="symbols, comma separated" value={symbols} onChange={(e) => setSymbols(e.target.value)} size={24} />
          <input
            className={inputCls}
            type="number"
            min={1}
            max={50}
            value={budget}
            onChange={(e) => setBudget(Number(e.target.value))}
            size={4}
          />
          <button
            disabled={busy || symbolList.length === 0}
            onClick={runNightly}
            className="rounded border border-amber-signal px-3 py-1 text-xs uppercase tracking-widest text-amber-signal hover:bg-amber-signal/10 disabled:opacity-50"
          >
            {busy ? "running…" : "Run nightly batch"}
          </button>
        </div>
      </Panel>

      {error && <ErrorBox error={error} />}

      {lastRun && (
        <Panel title={`Last run — ${lastRun.date}`}>
          <div className="mb-3 flex flex-wrap gap-4 text-sm">
            <span>tested <span className="figure text-ink-100">{lastRun.tallies.tested}</span></span>
            <span>rejected <span className="figure text-ink-100">{lastRun.tallies.rejected}</span></span>
            <span>needs more data <span className="figure text-amber-signal">{lastRun.tallies.needs_more_data}</span></span>
            <span>passed <span className="figure text-gain">{lastRun.tallies.passed}</span></span>
            <span>skipped (already tested) <span className="figure text-ink-400">{lastRun.skipped_novelty}</span></span>
          </div>
          <DataTable
            columns={["strategy", "symbols", "classification", "confidence", "sharpe", "rationale"]}
            rows={lastRun.tested.map((t) => [
              t.hypothesis.strategy,
              t.hypothesis.symbols.join(" "),
              <span key="c" className={CLASS_TONE[t.classification] ?? "text-ink-100"}>
                {t.classification}
              </span>,
              t.confidence,
              fmt.signed(t.headline.sharpe as number | null),
              <span key="r" className="max-w-xs truncate text-xs text-ink-400" title={t.hypothesis.rationale}>
                {t.hypothesis.rationale}
              </span>,
            ])}
          />
          {lastRun.errors.length > 0 && (
            <p className="mt-2 text-xs text-loss">
              {lastRun.errors.length} hypothesis run{lastRun.errors.length === 1 ? "" : "s"} errored and were skipped
              — the rest of the batch still completed.
            </p>
          )}
        </Panel>
      )}

      <Panel title={`Pending hypotheses (${queue?.length ?? 0})`}>
        {!queue && <Loading label="loading queue" />}
        {queue && (
          <DataTable
            columns={["strategy", "symbols", "rationale"]}
            rows={queue.map((h) => [
              String(h.strategy),
              (h.symbols as string[]).join(" "),
              <span key="r" className="text-xs text-ink-400">{String(h.rationale)}</span>,
            ])}
          />
        )}
      </Panel>

      <Panel title="Recent reports">
        {!reports && <Loading label="loading reports" />}
        {reports && (
          <DataTable
            columns={["date", "tested", "rejected", "needs data", "passed"]}
            rows={reports.map((r) => [
              r.date,
              String(r.tallies.tested),
              String(r.tallies.rejected),
              String(r.tallies.needs_more_data),
              <span key="p" className="text-gain">{r.tallies.passed}</span>,
            ])}
          />
        )}
      </Panel>
    </div>
  );
}
