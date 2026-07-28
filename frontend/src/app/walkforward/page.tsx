"use client";
/** Walk-forward index: fold statistics per experiment, one click to the timeline. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fmt, type ExperimentSummary } from "@/lib/api";
import { DataTable, ErrorBox, Loading, Panel } from "@/components/ui";

export default function WalkForwardPage() {
  const [rows, setRows] = useState<ExperimentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.experiments().then(setRows).catch((e) => setError(String(e))); }, []);
  if (error) return <ErrorBox error={error} />;
  if (!rows) return <Loading label="loading walk-forward runs" />;
  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Walk forward</h1>
      <Panel title="Out-of-sample validation by experiment — open the timeline to inspect every fold and trade">
        <DataTable
          columns={["experiment", "strategy", "val sharpe mean", "holdout sharpe", "view"]}
          rows={rows.map((e) => [
            e.id, e.strategy,
            fmt.signed(e.val_sharpe_mean),
            fmt.signed(e.final_sharpe),
            <Link key="x" href={`/experiments/${e.id}?tab=Walk%20Forward`} className="text-amber-signal hover:underline">fold timeline →</Link>,
          ])}
        />
      </Panel>
    </div>
  );
}
