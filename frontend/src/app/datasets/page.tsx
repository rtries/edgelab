"use client";
/** Dataset explorer index. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fmt, type DatasetRow } from "@/lib/api";
import { DataTable, ErrorBox, Loading, Panel } from "@/components/ui";

export default function DatasetsPage() {
  const [rows, setRows] = useState<DatasetRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.datasets().then(setRows).catch((e) => setError(String(e)));
  }, []);
  if (error) return <ErrorBox error={error} />;
  if (!rows) return <Loading label="loading datasets" />;
  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Datasets</h1>
      <Panel title="Imported data — raw prices only; adjustments are per-run and recorded in manifests">
        <DataTable
          columns={["symbol", "timeframe", "rows", "start", "end", "sources", "checksum", "updated"]}
          rows={rows.map((d) => [
            <Link key="s" href={`/datasets/${d.timeframe}/${d.symbol}`} className="text-amber-signal hover:underline">{d.symbol}</Link>,
            d.timeframe,
            String(d.rows),
            fmt.date(d.start),
            fmt.date(d.end),
            d.sources.join(", "),
            fmt.short(d.checksum, 16),
            fmt.date(d.updated_at),
          ])}
        />
      </Panel>
    </div>
  );
}
