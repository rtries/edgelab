"use client";
/** Deployment registry: every experiment promoted toward paper/live,
 * with its status and review flag. Nothing here is a trading control —
 * transitions happen on the deployment detail page, one deliberate step
 * at a time. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fmt, type DeploymentRow } from "@/lib/api";
import { ConfidenceStamp, DataTable, ErrorBox, Loading, Panel, Tag } from "@/components/ui";

const STATUS_TONE: Record<string, string> = {
  proposed: "text-ink-400",
  paper: "text-amber-signal",
  live: "text-gain",
  review: "text-loss",
  rejected: "text-ink-400",
  retired: "text-ink-400",
};

export default function DeploymentsPage() {
  const [rows, setRows] = useState<DeploymentRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.deployments().then(setRows).catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Deployments</h1>
      <p className="text-xs text-ink-400">
        Immutable configs promoted from the experiment registry. Each id is a
        hash of its config block — changing anything creates a new
        deployment. Status moves proposed → paper → live → review/retired,
        gated by confidence and paper evidence.
      </p>
      {error && <ErrorBox error={error} />}
      {!rows && !error && <Loading label="loading deployments" />}
      {rows && (
        <Panel title={`${rows.length} deployment${rows.length === 1 ? "" : "s"}`}>
          <DataTable
            columns={["id", "created", "strategy", "symbols", "confidence", "status", "review"]}
            rows={rows.map((d) => [
              <Link key="id" href={`/deployments/${d.id}`} className="text-amber-signal hover:underline">
                {d.id}
              </Link>,
              fmt.date(d.created_at),
              d.strategy,
              d.symbols.join(" "),
              <ConfidenceStamp key="c" level={d.confidence} size="sm" />,
              <span key="s" className={STATUS_TONE[d.status] ?? "text-ink-100"}>
                {d.status}
              </span>,
              d.review_required ? <Tag key="r">review needed</Tag> : <span key="r">—</span>,
            ])}
          />
        </Panel>
      )}
    </div>
  );
}
