"use client";
/** History: the full chronological research trail. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fmt, type ExperimentSummary } from "@/lib/api";
import { ConfidenceStamp, ErrorBox, Loading, Panel } from "@/components/ui";

export default function HistoryPage() {
  const [rows, setRows] = useState<ExperimentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.experiments().then(setRows).catch((e) => setError(String(e)));
  }, []);
  if (error) return <ErrorBox error={error} />;
  if (!rows) return <Loading label="loading history" />;
  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">History</h1>
      <Panel title="Every run, newest first — the registry forgets nothing">
        <ol className="space-y-2">
          {rows.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-3 border-b border-ink-800/60 pb-2 text-sm last:border-0">
              <span className="figure text-xs text-ink-400">{fmt.time(e.created_at)}</span>
              <Link href={`/experiments/${e.id}`} className="figure text-amber-signal hover:underline">{e.id}</Link>
              <span>{e.strategy}</span>
              <span className="figure text-xs text-ink-400">{e.symbols.join(" ")} · {Object.entries(e.selected_params).map(([k, v]) => `${k}=${v}`).join(" ")}</span>
              <ConfidenceStamp level={e.confidence} size="sm" />
              {e.n_warnings > 0 && <span className="text-xs text-loss">{e.n_warnings} warnings</span>}
            </li>
          ))}
        </ol>
      </Panel>
    </div>
  );
}
