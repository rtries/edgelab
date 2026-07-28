"use client";
/** Dashboard: the state of the research program at a glance. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fmt, type DatasetRow, type ExperimentSummary, type Note } from "@/lib/api";
import { ConfidenceStamp, DataTable, ErrorBox, Loading, Panel, Stat, Tag } from "@/components/ui";

export default function Dashboard() {
  const [experiments, setExperiments] = useState<ExperimentSummary[] | null>(null);
  const [datasets, setDatasets] = useState<DatasetRow[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.experiments(), api.datasets(), api.notes()])
      .then(([e, d, n]) => {
        setExperiments(e);
        setDatasets(d);
        setNotes(n);
      })
      .catch((err) => setError(String(err)));
  }, []);

  if (error) return <ErrorBox error={error} />;
  if (!experiments) return <Loading label="loading workspace" />;

  const byConfidence = (level: string) =>
    experiments.filter((e) => e.confidence === level).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-lg tracking-wide">Research dashboard</h1>
        <div className="flex gap-6">
          <Stat label="experiments" value={String(experiments.length)} />
          <Stat label="datasets" value={String(datasets.length)} />
          <Stat label="strong" value={String(byConfidence("strong"))} tone="gain" />
          <Stat label="moderate" value={String(byConfidence("moderate"))} tone="amber" />
          <Stat label="weak/insuff." value={String(byConfidence("weak") + byConfidence("insufficient"))} tone="loss" />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Recent experiments" className="lg:col-span-2">
          <DataTable
            columns={["id", "strategy", "symbols", "dev sharpe", "val mean", "holdout", "confidence", "⚠"]}
            rows={experiments.slice(0, 8).map((e) => [
              <Link key="id" href={`/experiments/${e.id}`} className="text-amber-signal hover:underline">{e.id}</Link>,
              e.strategy,
              e.symbols.join(" "),
              <span key="s" className={Number(e.metrics.sharpe) >= 0 ? "text-gain" : "text-loss"}>{fmt.signed(e.metrics.sharpe)}</span>,
              fmt.signed(e.val_sharpe_mean),
              <span key="h" className={Number(e.final_sharpe) >= 0 ? "text-gain" : "text-loss"}>{fmt.signed(e.final_sharpe)}</span>,
              <ConfidenceStamp key="c" level={e.confidence} size="sm" />,
              e.n_warnings > 0 ? <span className="text-loss">{e.n_warnings}</span> : "0",
            ])}
          />
        </Panel>

        <div className="space-y-4">
          <Panel title="Datasets">
            {datasets.length === 0 ? (
              <p className="text-sm text-ink-400">
                No data imported. Run <span className="figure text-ink-100">python scripts/seed_research.py</span>.
              </p>
            ) : (
              datasets.map((d) => (
                <Link
                  key={`${d.timeframe}/${d.symbol}`}
                  href={`/datasets/${d.timeframe}/${d.symbol}`}
                  className="flex items-center justify-between border-b border-ink-800/60 py-1.5 text-sm last:border-0 hover:text-amber-signal"
                >
                  <span className="figure">{d.symbol} · {d.timeframe}</span>
                  <span className="figure text-xs text-ink-400">{d.rows} bars</span>
                </Link>
              ))
            )}
          </Panel>
          <Panel title="Latest notes" right={<Link href="/notes" className="text-xs text-amber-signal hover:underline">all</Link>}>
            {notes.length === 0 ? (
              <p className="text-sm text-ink-400">No notes yet — the best researchers write down what didn&apos;t work.</p>
            ) : (
              notes.slice(0, 4).map((n) => (
                <div key={n.id} className="border-b border-ink-800/60 py-1.5 text-sm last:border-0">
                  <div className="flex items-center justify-between">
                    <span>{n.title}</span>
                    <span className="figure text-[10px] text-ink-400">{fmt.date(n.created_at)}</span>
                  </div>
                  <div className="mt-0.5 flex gap-1">{n.tags.map((t) => <Tag key={t}>{t}</Tag>)}</div>
                </div>
              ))
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
