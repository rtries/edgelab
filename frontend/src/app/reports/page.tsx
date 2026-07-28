"use client";
/** Reports: one click from any experiment to a professional PDF. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fmt, type ExperimentSummary } from "@/lib/api";
import { ConfidenceStamp, DataTable, ErrorBox, Loading, Panel } from "@/components/ui";

export default function ReportsPage() {
  const [rows, setRows] = useState<ExperimentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.experiments().then(setRows).catch((e) => setError(String(e)));
  }, []);
  if (error) return <ErrorBox error={error} />;
  if (!rows) return <Loading label="loading reports" />;
  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Reports</h1>
      <Panel title="Every experiment exports the same structured report — exec summary, methodology, validation, charts, warnings, confidence">
        <DataTable
          columns={["experiment", "strategy", "confidence", "generated", "export"]}
          rows={rows.map((e) => [
            <Link key="l" href={`/experiments/${e.id}?tab=Report`} className="text-amber-signal hover:underline">{e.id}</Link>,
            e.strategy,
            <ConfidenceStamp key="c" level={e.confidence} size="sm" />,
            fmt.time(e.created_at),
            <button key="pdf" onClick={() => api.downloadPdf(e.id)} className="rounded border border-amber-signal px-2 py-0.5 text-[10px] uppercase tracking-widest text-amber-signal hover:bg-amber-signal hover:text-ink-950">PDF</button>,
          ])}
        />
      </Panel>
    </div>
  );
}
