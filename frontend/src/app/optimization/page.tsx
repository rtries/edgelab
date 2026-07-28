"use client";
/** Optimization runs: each experiment's parameter search, one click to the explorer. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fmt, type ExperimentSummary } from "@/lib/api";
import { DataTable, ErrorBox, Loading, Panel } from "@/components/ui";

export default function OptimizationPage() {
  const [rows, setRows] = useState<ExperimentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.experiments().then(setRows).catch((e) => setError(String(e))); }, []);
  if (error) return <ErrorBox error={error} />;
  if (!rows) return <Loading label="loading optimization runs" />;
  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Optimization runs</h1>
      <Panel title="Parameter searches by experiment — open the explorer for heatmaps and robustness">
        <DataTable
          columns={["experiment", "strategy", "selected params", "dev sharpe", "explore"]}
          rows={rows.map((e) => [
            e.id, e.strategy,
            Object.entries(e.selected_params).map(([k, v]) => `${k}=${v}`).join(" "),
            fmt.signed(e.metrics.sharpe),
            <Link key="x" href={`/experiments/${e.id}?tab=Parameters`} className="text-amber-signal hover:underline">parameter explorer →</Link>,
          ])}
        />
      </Panel>
    </div>
  );
}
