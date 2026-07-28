"use client";
/** Strategy catalog: engine-verification examples with their parameter spaces. */
import { useEffect, useState } from "react";
import { api, type StrategyInfo } from "@/lib/api";
import { DataTable, ErrorBox, Loading, Panel } from "@/components/ui";

export default function StrategiesPage() {
  const [rows, setRows] = useState<StrategyInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.strategies().then(setRows).catch((e) => setError(String(e)));
  }, []);
  if (error) return <ErrorBox error={error} />;
  if (!rows) return <Loading label="loading strategies" />;
  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Strategies</h1>
      <p className="text-xs text-ink-400">
        Built-in examples exist to verify engine mechanics, not to make money. Author strategies against the SDK (docs/DATA.md) and they appear here.
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        {rows.map((s) => (
          <Panel key={s.name} title={s.name}>
            <p className="mb-3 whitespace-pre-line text-xs text-ink-400">{s.description}</p>
            <DataTable
              columns={["param", "type", "default", "min", "max", "step"]}
              rows={s.params.map((p) => [
                p.name, p.type, String(p.default),
                p.min === null ? "—" : String(p.min),
                p.max === null ? "—" : String(p.max),
                p.step === null ? "—" : String(p.step),
              ])}
            />
          </Panel>
        ))}
      </div>
    </div>
  );
}
