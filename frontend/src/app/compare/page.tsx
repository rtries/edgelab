"use client";
/** Strategy comparison: pick experiments, see them side by side —
 * equity, drawdowns, monthly returns, trade distributions, exposure,
 * Monte Carlo intervals, and validation scores. */
import { useEffect, useMemo, useState } from "react";
import { api, fmt, type Experiment, type ExperimentSummary } from "@/lib/api";
import { Histogram, LineChart, MonthlyGrid } from "@/components/charts";
import { ConfidenceStamp, DataTable, ErrorBox, Loading, Panel } from "@/components/ui";

const PALETTE = ["#e8a33d", "#35c48d", "#5b8def", "#e35d6a", "#b48ce8", "#8ce8dd"];

export default function ComparePage() {
  const [summaries, setSummaries] = useState<ExperimentSummary[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [experiments, setExperiments] = useState<Record<string, Experiment>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.experiments().then((rows) => {
      setSummaries(rows);
      setSelected(rows.slice(0, Math.min(3, rows.length)).map((r) => r.id));
    }).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    for (const id of selected) {
      if (!experiments[id]) {
        api.experiment(id).then((exp) => setExperiments((m) => ({ ...m, [id]: exp }))).catch((e) => setError(String(e)));
      }
    }
  }, [selected, experiments]);

  const loaded = useMemo(
    () => selected.map((id) => experiments[id]).filter((e): e is Experiment => !!e),
    [selected, experiments],
  );

  if (error) return <ErrorBox error={error} />;
  if (!summaries) return <Loading label="loading experiments" />;

  const colorOf = (id: string) => PALETTE[selected.indexOf(id) % PALETTE.length];

  // Normalize each equity curve to 1.0 at start so different capital bases overlay honestly.
  const normalized = loaded.map((exp) => {
    const first = exp.development.equity.find((p) => p[1] !== null)?.[1] ?? 1;
    return {
      exp,
      points: exp.development.equity.map(([t, v]) => [t, v === null ? null : v / first] as [string, number | null]),
    };
  });

  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Strategy comparison</h1>
      <Panel title="Select experiments (click to toggle)">
        <div className="flex flex-wrap gap-2">
          {summaries.map((s) => {
            const on = selected.includes(s.id);
            return (
              <button
                key={s.id}
                onClick={() => setSelected((cur) => (on ? cur.filter((x) => x !== s.id) : [...cur, s.id]))}
                className={`figure rounded border px-2 py-1 text-xs transition-colors ${
                  on ? "border-amber-signal text-ink-100" : "border-ink-800 text-ink-400 hover:border-ink-400"
                }`}
                style={on ? { borderColor: colorOf(s.id) } : undefined}
              >
                <span style={on ? { color: colorOf(s.id) } : undefined}>{s.strategy}</span>
                <span className="ml-1 text-ink-400">{s.id.slice(0, 6)} · {s.symbols.join(" ")}</span>
              </button>
            );
          })}
        </div>
      </Panel>

      {loaded.length === 0 ? (
        <p className="text-sm text-ink-400">Select at least one experiment.</p>
      ) : (
        <>
          <Panel title="Equity, normalized to 1.0 at start (development ranges)">
            <LineChart
              series={normalized[0].points}
              color={colorOf(normalized[0].exp.id)}
              overlays={normalized.slice(1).map(({ exp, points }) => ({ points, color: colorOf(exp.id), label: exp.id }))}
              yFormat={(v) => fmt.num(v, 2)}
              baseline={1}
            />
            <div className="mt-1 flex flex-wrap gap-3 text-[11px]">
              {loaded.map((exp) => (
                <span key={exp.id} style={{ color: colorOf(exp.id) }} className="figure">■ {exp.strategy} ({exp.id.slice(0, 6)})</span>
              ))}
            </div>
          </Panel>

          <Panel title="Side by side — validation score is the number that matters">
            <DataTable
              columns={["strategy", "dev sharpe", "max dd", "PF", "exposure", "val mean", "val consistency", "MC sharpe q2.5", "holdout sharpe", "confidence", "⚠"]}
              rows={loaded.map((exp) => {
                const mcLower = Object.values(exp.montecarlo.cis)
                  .map((m) => m.sharpe?.["q0.025"])
                  .filter((v): v is number => v !== null && v !== undefined)
                  .reduce<number | null>((acc, v) => (acc === null ? v : Math.min(acc, v)), null);
                return [
                  <span key="n" style={{ color: colorOf(exp.id) }}>{exp.strategy}</span>,
                  fmt.signed(exp.development.metrics.sharpe),
                  fmt.pct(exp.development.metrics.max_drawdown),
                  fmt.num(exp.development.metrics.profit_factor),
                  fmt.pct(exp.development.metrics.exposure),
                  fmt.signed(exp.walkforward.aggregate.sharpe_mean),
                  fmt.num(exp.walkforward.validation_consistency),
                  fmt.signed(mcLower),
                  <span key="h" className={(exp.final_test.sharpe ?? 0) >= 0 ? "text-gain" : "text-loss"}>{fmt.signed(exp.final_test.sharpe)}</span>,
                  <ConfidenceStamp key="c" level={exp.confidence.level} size="sm" />,
                  String(exp.warnings.length),
                ];
              })}
            />
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            {loaded.map((exp) => (
              <Panel key={exp.id} title={`${exp.strategy} — monthly returns`}>
                <MonthlyGrid rows={exp.development.monthly_returns} />
              </Panel>
            ))}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {loaded.map((exp) => (
              <Panel key={exp.id} title={`${exp.strategy} — trade P&L distribution (${exp.development.trade_pnls.length} trades)`}>
                <Histogram values={exp.development.trade_pnls} zeroSplit />
              </Panel>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
