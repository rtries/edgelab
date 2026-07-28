"use client";
/** Morning Brief — what you'd want to see opening EdgeLab: deployment
 * health, drift alerts, and last night's research, in one place. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fmt, type MorningDashboard } from "@/lib/api";
import { DataTable, ErrorBox, Loading, Panel, Stat } from "@/components/ui";

const TONE: Record<string, string> = {
  healthy: "text-gain",
  weakening: "text-amber-signal",
  unstable: "text-loss",
  retire_recommended: "text-loss",
};

export default function MorningBriefPage() {
  const [data, setData] = useState<MorningDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.morning().then(setData).catch((e) => setError(String(e)));
  }, []);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading label="loading morning brief" />;

  const active = data.deployments.filter((d) => d.status === "paper" || d.status === "live");
  const research = data.latest_research;

  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Morning Brief</h1>

      {data.emergency_stop && (
        <div className="rounded border border-loss bg-loss/10 p-3 text-sm text-loss">
          Emergency stop is ACTIVE — no deployment is submitting new orders.{" "}
          <Link href="/monitoring" className="underline">Go to Live Monitoring</Link>.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="Deployments">
          <div className="flex flex-wrap gap-6">
            <Stat label="active" value={String(active.length)} />
            <Stat label="alerts" value={String(data.deployment_alerts.length)} tone={data.deployment_alerts.length ? "loss" : "gain"} />
          </div>
        </Panel>
        <Panel title="Last night's research">
          {research ? (
            <div className="flex flex-wrap gap-6">
              <Stat label="tested" value={String(research.tallies.tested)} />
              <Stat label="rejected" value={String(research.tallies.rejected)} />
              <Stat label="needs data" value={String(research.tallies.needs_more_data)} tone="amber" />
              <Stat label="passed" value={String(research.tallies.passed)} tone="gain" />
            </div>
          ) : (
            <p className="text-sm text-ink-400">No nightly run yet.</p>
          )}
        </Panel>
        <Panel title="Quick links">
          <div className="flex flex-col gap-1 text-sm">
            <Link href="/deployments" className="text-amber-signal hover:underline">Deployments →</Link>
            <Link href="/edge-health" className="text-amber-signal hover:underline">Edge Health →</Link>
            <Link href="/research-queue" className="text-amber-signal hover:underline">Research Queue →</Link>
            <Link href="/monitoring" className="text-amber-signal hover:underline">Live Monitoring →</Link>
          </div>
        </Panel>
      </div>

      <Panel title="Deployment health alerts">
        {data.deployment_alerts.length === 0 ? (
          <p className="text-sm text-ink-400">No alerts — every active deployment is healthy.</p>
        ) : (
          <DataTable
            columns={["deployment", "status", "top trigger"]}
            rows={data.deployment_alerts.map((a) => [
              <Link key="id" href={`/deployments/${a.deployment_id}?tab=Drift`} className="text-amber-signal hover:underline">
                {a.deployment_id}
              </Link>,
              <span key="s" className={TONE[a.status]}>{a.status}</span>,
              a.triggers[0]?.message ?? "—",
            ])}
          />
        )}
      </Panel>

      {research && research.tested.filter((t) => t.classification === "passed").length > 0 && (
        <Panel title="New validated ideas">
          <DataTable
            columns={["strategy", "symbols", "confidence", "sharpe", "experiment"]}
            rows={research.tested
              .filter((t) => t.classification === "passed")
              .map((t) => [
                t.hypothesis.strategy,
                t.hypothesis.symbols.join(" "),
                t.confidence,
                fmt.signed(t.headline.sharpe as number | null),
                <Link key="e" href={`/experiments/${t.experiment_id}`} className="text-amber-signal hover:underline">
                  {t.experiment_id}
                </Link>,
              ])}
          />
        </Panel>
      )}

      <Panel title="Strategies recommended for retirement">
        {(() => {
          const retire = data.deployment_alerts.filter((a) => a.status === "retire_recommended");
          return retire.length === 0 ? (
            <p className="text-sm text-ink-400">None.</p>
          ) : (
            <DataTable
              columns={["deployment", "evidence"]}
              rows={retire.map((a) => [
                <Link key="id" href={`/deployments/${a.deployment_id}?tab=Drift`} className="text-amber-signal hover:underline">
                  {a.deployment_id}
                </Link>,
                a.triggers.map((t) => t.code).join(", "),
              ])}
            />
          );
        })()}
      </Panel>
    </div>
  );
}
