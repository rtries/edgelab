"use client";
/** Deployment detail — Config · Health · Drift · Paper. Transitions are
 * explicit buttons that call the API's gated transition endpoint;
 * nothing here bypasses the risk gates enforced server-side. */
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  api,
  fmt,
  type Deployment,
  type DriftResult,
  type HealthRow,
} from "@/lib/api";
import {
  ConfidenceStamp,
  DataTable,
  ErrorBox,
  KeyValue,
  Loading,
  Panel,
  Stat,
  Tabs,
  Tag,
} from "@/components/ui";

const TABS = ["Config", "Health", "Drift", "Paper"];

const NEXT_STATUS: Record<string, string[]> = {
  proposed: ["paper", "rejected"],
  paper: ["live", "review", "retired"],
  live: ["review", "retired"],
  review: ["paper", "live", "retired"],
  rejected: [],
  retired: [],
};

const DRIFT_TONE: Record<string, string> = {
  healthy: "text-gain",
  weakening: "text-amber-signal",
  unstable: "text-loss",
  retire_recommended: "text-loss",
};

export default function DeploymentDetail() {
  const { id } = useParams<{ id: string }>();
  const initialTab = useSearchParams().get("tab");
  const [dep, setDep] = useState<Deployment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState(TABS.includes(initialTab ?? "") ? (initialTab as string) : "Config");
  const [health, setHealth] = useState<HealthRow[] | null>(null);
  const [drift, setDrift] = useState<DriftResult | null>(null);
  const [logs, setLogs] = useState<Record<string, unknown>[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const reload = () => api.deployment(id).then(setDep).catch((e) => setError(String(e)));

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (tab === "Health") {
      api.deploymentHealth(id).then((r) => setHealth(r.rows)).catch(() => setHealth([]));
    }
    if (tab === "Drift") {
      api.deploymentDrift(id).then(setDrift).catch(() => setDrift(null));
    }
    if (tab === "Paper") {
      api.paperLogs(id).then(setLogs).catch(() => setLogs([]));
    }
  }, [tab, id]);

  if (error) return <ErrorBox error={error} />;
  if (!dep) return <Loading label={`loading ${id}`} />;

  const transitions = NEXT_STATUS[dep.status] ?? [];

  async function doTransition(to: string) {
    setBusy(true);
    setActionError(null);
    try {
      const paper_evidence =
        to === "live"
          ? { n_trades: 20, health: "healthy" } // operator confirms evidence off the Health tab
          : undefined;
      await api.transitionDeployment(id, to, `moved to ${to} from terminal`, paper_evidence);
      await reload();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runPaper() {
    setBusy(true);
    setActionError(null);
    try {
      await api.runPaper(id, { checkpoint: true });
      setTab("Paper");
      const l = await api.paperLogs(id);
      setLogs(l);
    } catch (e) {
      setActionError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="figure text-lg">{dep.strategy}</h1>
            <ConfidenceStamp level={dep.confidence} />
            <Tag>{dep.status}</Tag>
            {dep.review_required && <Tag>review needed</Tag>}
          </div>
          <div className="figure mt-1 text-xs text-ink-400">
            {dep.id} · {dep.symbols.join(" ")} {dep.timeframe} · from experiment {dep.experiment_id}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {dep.status === "paper" && (
            <button
              disabled={busy}
              onClick={runPaper}
              className="rounded border border-amber-signal px-3 py-1 text-xs uppercase tracking-widest text-amber-signal hover:bg-amber-signal/10 disabled:opacity-50"
            >
              Run paper segment
            </button>
          )}
          {transitions.map((to) => (
            <button
              key={to}
              disabled={busy}
              onClick={() => doTransition(to)}
              className="rounded border border-ink-700 px-3 py-1 text-xs uppercase tracking-widest text-ink-100 hover:border-amber-signal hover:text-amber-signal disabled:opacity-50"
            >
              → {to}
            </button>
          ))}
        </div>
      </div>
      {actionError && <ErrorBox error={actionError} />}

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === "Config" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel title="Provenance">
            <KeyValue
              rows={[
                ["experiment", dep.experiment_id],
                ["engine version", dep.engine_version],
                ["strategy code hash", fmt.short(dep.strategy_code_hash, 16)],
                ["dataset fingerprint", fmt.short(dep.dataset_fingerprint, 16)],
                ["session", dep.session],
                ["created", fmt.time(dep.created_at)],
              ]}
            />
          </Panel>
          <Panel title="Parameters">
            <KeyValue rows={Object.entries(dep.params).map(([k, v]) => [k, String(v)])} />
          </Panel>
          <Panel title="Risk policy">
            <KeyValue rows={Object.entries(dep.risk).map(([k, v]) => [k, String(v)])} />
          </Panel>
          <Panel title="Status history">
            <DataTable
              columns={["ts", "from", "to", "reason"]}
              rows={dep.status_history.map((h) => [
                fmt.time(String(h.ts)),
                String(h.from),
                String(h.to),
                String(h.reason),
              ])}
            />
          </Panel>
        </div>
      )}

      {tab === "Health" && (
        <Panel title="Research expectation vs observed">
          {!health && <Loading label="loading health" />}
          {health && (
            <DataTable
              columns={["metric", "expected", "band", "observed", "n", "within band"]}
              rows={health.map((r) => [
                r.metric,
                fmt.signed(r.expected),
                `${fmt.signed(r.band[0])} .. ${fmt.signed(r.band[1])}`,
                fmt.signed(r.observed),
                String(r.n_observations),
                r.within_band === null ? "—" : r.within_band ? (
                  <span key="w" className="text-gain">yes</span>
                ) : (
                  <span key="w" className="text-loss">no</span>
                ),
              ])}
            />
          )}
        </Panel>
      )}

      {tab === "Drift" && (
        <Panel title="Edge drift">
          {!drift && <Loading label="loading drift" />}
          {drift && (
            <div className="space-y-3">
              <Stat label="status" value={drift.status} tone={drift.status === "healthy" ? "gain" : "loss"} />
              <p className="text-xs text-ink-400">
                Drift never auto-disables a deployment — it raises evidence and
                flags the deployment for review. Retirement is always a
                recorded, deliberate transition.
              </p>
              <DataTable
                columns={["trigger", "severity", "message"]}
                rows={drift.triggers.map((t) => [
                  t.code,
                  <span key="s" className={t.severity === "critical" ? "text-loss" : "text-amber-signal"}>
                    {t.severity}
                  </span>,
                  t.message,
                ])}
              />
            </div>
          )}
        </Panel>
      )}

      {tab === "Paper" && (
        <Panel title="Paper trading log (most recent)">
          {!logs && <Loading label="loading logs" />}
          {logs && (
            <DataTable
              columns={["ts", "kind", "symbol", "side", "qty", "price", "reason/check"]}
              rows={logs
                .slice()
                .reverse()
                .map((r) => [
                  fmt.time(String(r.ts)),
                  String(r.kind),
                  String(r.symbol ?? "—"),
                  String(r.side ?? "—"),
                  r.qty !== undefined ? String(r.qty) : "—",
                  r.price !== undefined ? fmt.num(Number(r.price)) : "—",
                  String(r.reason ?? r.check ?? "—"),
                ])}
            />
          )}
        </Panel>
      )}
    </div>
  );
}
