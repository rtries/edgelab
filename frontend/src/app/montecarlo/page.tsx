"use client";
/** Monte Carlo index: robustness intervals per experiment, one click to the fan. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fmt, type ExperimentSummary } from "@/lib/api";
import { DataTable, ErrorBox, Loading, Panel } from "@/components/ui";

export default function MonteCarloPage() {
  const [rows, setRows] = useState<ExperimentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.experiments().then(setRows).catch((e) => setError(String(e))); }, []);
  if (error) return <ErrorBox error={error} />;
  if (!rows) return <Loading label="loading Monte Carlo runs" />;
  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Monte Carlo</h1>
      <Panel title="Resampling robustness by experiment — sharpe q2.5 is the honest lower bound">
        <DataTable
          columns={["experiment", "strategy", "mc sharpe q2.5", "view"]}
          rows={rows.map((e) => [
            e.id, e.strategy,
            <span key="q" className={Number(e.mc_sharpe_lower) >= 0 ? "text-gain" : "text-loss"}>{fmt.signed(e.mc_sharpe_lower)}</span>,
            <Link key="x" href={`/experiments/${e.id}?tab=Monte%20Carlo`} className="text-amber-signal hover:underline">fan chart →</Link>,
          ])}
        />
      </Panel>
    </div>
  );
}
