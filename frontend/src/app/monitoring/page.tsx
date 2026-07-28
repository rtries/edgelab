"use client";
/** Live Monitoring — the emergency stop and a cross-deployment view of
 * paper/live activity. The kill switch calls the ops API directly; it
 * blocks new orders on the next processed event for every deployment,
 * never mid-fill. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fmt, type DeploymentRow } from "@/lib/api";
import { DataTable, ErrorBox, Loading, Panel, Stat } from "@/components/ui";

export default function MonitoringPage() {
  const [stopped, setStopped] = useState<boolean | null>(null);
  const [deployments, setDeployments] = useState<DeploymentRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = () => {
    api.emergencyStopStatus().then((r) => setStopped(r.emergency_stop)).catch((e) => setError(String(e)));
    api.deployments().then(setDeployments).catch((e) => setError(String(e)));
  };

  useEffect(() => {
    reload();
  }, []);

  async function toggle() {
    setBusy(true);
    try {
      const r = stopped ? await api.emergencyStopOff() : await api.emergencyStopOn();
      setStopped(r.emergency_stop);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const active = deployments?.filter((d) => d.status === "paper" || d.status === "live") ?? [];

  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Live Monitoring</h1>
      {error && <ErrorBox error={error} />}

      <Panel title="Emergency stop">
        <div className="flex items-center justify-between gap-4">
          <div>
            <Stat
              label="global kill switch"
              value={stopped === null ? "…" : stopped ? "ACTIVE" : "off"}
              tone={stopped ? "loss" : "gain"}
            />
            <p className="mt-2 max-w-md text-xs text-ink-400">
              When active, every deployment&apos;s risk chain rejects new signals
              with evidence logged as <span className="figure">emergency_stop</span>.
              Working orders already accepted still fill normally. This never
              disables a deployment&apos;s config — turning the switch off
              resumes exactly where it left off.
            </p>
          </div>
          <button
            disabled={busy || stopped === null}
            onClick={toggle}
            className={`rounded border px-4 py-2 text-xs uppercase tracking-widest disabled:opacity-50 ${
              stopped
                ? "border-gain text-gain hover:bg-gain/10"
                : "border-loss text-loss hover:bg-loss/10"
            }`}
          >
            {stopped ? "Resume trading" : "Stop all trading"}
          </button>
        </div>
      </Panel>

      <Panel title={`Active deployments (${active.length})`}>
        {!deployments && <Loading label="loading deployments" />}
        {deployments && (
          <DataTable
            columns={["id", "strategy", "symbols", "status", "review"]}
            rows={active.map((d) => [
              <Link key="id" href={`/deployments/${d.id}?tab=Paper`} className="text-amber-signal hover:underline">
                {d.id}
              </Link>,
              d.strategy,
              d.symbols.join(" "),
              d.status,
              d.review_required ? <span key="r" className="text-loss">flagged</span> : "—",
            ])}
          />
        )}
      </Panel>
    </div>
  );
}
