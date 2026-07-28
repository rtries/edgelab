"use client";
/** Edge Health board — drift status across every paper/live deployment
 * in one place. Retirement recommendations are exactly that:
 * recommendations. Nothing here disables anything automatically. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type DeploymentRow, type DriftResult } from "@/lib/api";
import { DataTable, ErrorBox, Loading, Panel, Stat } from "@/components/ui";

const TONE: Record<string, string> = {
  healthy: "text-gain",
  weakening: "text-amber-signal",
  unstable: "text-loss",
  retire_recommended: "text-loss",
};

export default function EdgeHealthPage() {
  const [deployments, setDeployments] = useState<DeploymentRow[] | null>(null);
  const [drifts, setDrifts] = useState<Record<string, DriftResult>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .deployments()
      .then(async (rows) => {
        setDeployments(rows);
        const active = rows.filter((d) => d.status === "paper" || d.status === "live");
        const results = await Promise.all(
          active.map((d) => api.deploymentDrift(d.id).catch(() => null)),
        );
        const map: Record<string, DriftResult> = {};
        active.forEach((d, i) => {
          const r = results[i];
          if (r) map[d.id] = r;
        });
        setDrifts(map);
      })
      .catch((e) => setError(String(e)));
  }, []);

  const active = deployments?.filter((d) => d.status === "paper" || d.status === "live") ?? [];
  const counts = { healthy: 0, weakening: 0, unstable: 0, retire_recommended: 0 };
  Object.values(drifts).forEach((d) => {
    counts[d.status] += 1;
  });

  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Edge Health</h1>
      {error && <ErrorBox error={error} />}

      <div className="flex flex-wrap gap-6">
        <Stat label="healthy" value={String(counts.healthy)} tone="gain" />
        <Stat label="weakening" value={String(counts.weakening)} tone="amber" />
        <Stat label="unstable" value={String(counts.unstable)} tone="loss" />
        <Stat label="retire recommended" value={String(counts.retire_recommended)} tone="loss" />
      </div>

      <Panel title="Deployments">
        {!deployments && <Loading label="loading" />}
        {deployments && (
          <DataTable
            columns={["id", "strategy", "status", "health", "top trigger"]}
            rows={active.map((d) => {
              const drift = drifts[d.id];
              return [
                <Link key="id" href={`/deployments/${d.id}?tab=Drift`} className="text-amber-signal hover:underline">
                  {d.id}
                </Link>,
                d.strategy,
                d.status,
                drift ? (
                  <span key="h" className={TONE[drift.status]}>{drift.status}</span>
                ) : (
                  "—"
                ),
                drift?.triggers[0]?.message ?? "—",
              ];
            })}
          />
        )}
      </Panel>
    </div>
  );
}
