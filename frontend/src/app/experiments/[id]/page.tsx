"use client";
/** Experiment detail — the core of the terminal. Tabs:
 * Overview · Walk Forward · Parameters · Monte Carlo · Regimes · Report.
 * Everything shown is read from the persisted experiment; nothing is
 * recomputed client-side. */
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, fmt, type Experiment } from "@/lib/api";
import {
  DrawdownChart,
  FanChart,
  FoldTimeline,
  Heatmap,
  Histogram,
  LineChart,
  MonthlyGrid,
} from "@/components/charts";
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

const TABS = ["Overview", "Walk Forward", "Parameters", "Monte Carlo", "Regimes", "Report"];

export default function ExperimentDetail() {
  const { id } = useParams<{ id: string }>();
  const initialTab = useSearchParams().get("tab");
  const [exp, setExp] = useState<Experiment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState(TABS.includes(initialTab ?? "") ? (initialTab as string) : "Overview");
  const [fold, setFold] = useState<number | null>(null);

  useEffect(() => {
    api.experiment(id).then(setExp).catch((e) => setError(String(e)));
  }, [id]);

  if (error) return <ErrorBox error={error} />;
  if (!exp) return <Loading label={`loading ${id}`} />;

  const dev = exp.development.metrics;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="figure text-lg">{exp.strategy}</h1>
            <ConfidenceStamp level={exp.confidence.level} />
            {exp.tags.map((t) => <Tag key={t}>{t}</Tag>)}
          </div>
          <div className="figure mt-1 text-xs text-ink-400">
            {exp.id} · {exp.symbols.join(" ")} {exp.timeframe} · engine {exp.engine_version} · seed {exp.seed} ·{" "}
            {Object.entries(exp.selected_params).map(([k, v]) => `${k}=${v}`).join(" ")}
          </div>
        </div>
        <div className="flex items-center gap-6">
          <Stat label="dev sharpe" value={fmt.signed(dev.sharpe)} tone={dev.sharpe >= 0 ? "gain" : "loss"} />
          <Stat label="val mean" value={fmt.signed(exp.walkforward.aggregate.sharpe_mean)} />
          <Stat label="holdout" value={fmt.signed(exp.final_test.sharpe)} tone={(exp.final_test.sharpe ?? 0) >= 0 ? "gain" : "loss"} />
          <button onClick={() => api.downloadPdf(exp.id)} className="rounded border border-amber-signal px-3 py-1.5 text-xs uppercase tracking-widest text-amber-signal hover:bg-amber-signal hover:text-ink-950">
            Export PDF
          </button>
        </div>
      </div>

      {exp.warnings.length > 0 && (
        <div className="rounded border border-loss/40 bg-loss/5 p-2 text-xs">
          {exp.warnings.map((w) => (
            <div key={w.code} className="py-0.5">
              <span className={`figure mr-2 uppercase ${w.severity === "critical" ? "text-loss" : "text-amber-signal"}`}>[{w.severity}] {w.code}</span>
              <span className="text-ink-400">{w.message}</span>
            </div>
          ))}
        </div>
      )}

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === "Overview" && <Overview exp={exp} />}
      {tab === "Walk Forward" && <WalkForward exp={exp} fold={fold} setFold={setFold} />}
      {tab === "Parameters" && <Parameters exp={exp} />}
      {tab === "Monte Carlo" && <MonteCarlo exp={exp} />}
      {tab === "Regimes" && <Regimes exp={exp} />}
      {tab === "Report" && <Report exp={exp} />}
    </div>
  );
}

function MetricGrid({ metrics }: { metrics: Record<string, number> }) {
  const keys = ["sharpe", "sortino", "calmar", "max_drawdown", "profit_factor", "win_rate", "expectancy", "n_trades", "exposure", "cagr", "ulcer_index", "end_equity"];
  return (
    <div className="grid grid-cols-3 gap-x-6 gap-y-3 sm:grid-cols-4 lg:grid-cols-6">
      {keys.filter((k) => metrics[k] !== undefined && metrics[k] !== null).map((k) => (
        <Stat
          key={k}
          label={k.replace(/_/g, " ")}
          value={
            k === "max_drawdown" || k === "win_rate" || k === "exposure" || k === "cagr"
              ? fmt.pct(metrics[k])
              : k === "n_trades" || k === "end_equity"
                ? fmt.num(metrics[k], 0)
                : fmt.signed(metrics[k])
          }
          tone={k === "sharpe" ? (metrics[k] >= 0 ? "gain" : "loss") : "neutral"}
        />
      ))}
    </div>
  );
}

function Overview({ exp }: { exp: Experiment }) {
  return (
    <div className="space-y-4">
      <p className="rounded border border-ink-800 bg-ink-950 p-2 text-[11px] text-ink-400">{exp.development.note}</p>
      <Panel title="Development equity">
        <LineChart series={exp.development.equity} />
        <DrawdownChart series={exp.development.drawdown} />
      </Panel>
      <Panel title="Development metrics"><MetricGrid metrics={exp.development.metrics} /></Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Monthly returns"><MonthlyGrid rows={exp.development.monthly_returns} /></Panel>
        <Panel title="Trade P&L distribution">
          <Histogram values={exp.development.trade_pnls} zeroSplit format={(v) => fmt.num(v, 0)} />
          <div className="mt-1 text-[10px] text-ink-400">{exp.development.trade_pnls.length} closed trades (net of costs)</div>
        </Panel>
      </div>
      <Panel title="Exposure">
        <LineChart series={exp.development.exposure} height={120} color="var(--color-ink-400)" yFormat={(v) => fmt.pct(v, 0)} />
      </Panel>
      <Panel title="Final holdout — evaluated once, with the selected parameters">
        <MetricGrid metrics={exp.final_test} />
        <p className="mt-3 text-[11px] text-ink-400">
          Holdout range {fmt.date(exp.windows.holdout_range[0])} → {fmt.date(exp.windows.holdout_range[1])} ({exp.windows.test_size} bars) was reserved before any optimization ran.
        </p>
      </Panel>
    </div>
  );
}

function WalkForward({ exp, fold, setFold }: { exp: Experiment; fold: number | null; setFold: (i: number) => void }) {
  const selected = exp.walkforward.folds.find((f) => f.index === fold) ?? null;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Fold timeline — click a fold to inspect" className="lg:col-span-2">
          <FoldTimeline
            folds={exp.walkforward.folds}
            workRange={exp.windows.work_range}
            holdoutRange={exp.windows.holdout_range}
            selected={fold}
            onSelect={setFold}
          />
        </Panel>
        <Panel title="Aggregate (validation folds)">
          <KeyValue
            rows={[
              ["folds", String(exp.walkforward.aggregate.n_folds)],
              ["sharpe mean", fmt.signed(exp.walkforward.aggregate.sharpe_mean)],
              ["sharpe min", fmt.signed(exp.walkforward.aggregate.sharpe_min)],
              ["fraction positive", fmt.pct(exp.walkforward.aggregate.fraction_positive_objective)],
              ["consistency (std)", fmt.num(exp.walkforward.validation_consistency)],
            ]}
          />
        </Panel>
      </div>
      <Panel title="Parameter history">
        <DataTable
          columns={Object.keys(exp.walkforward.param_history[0] ?? { fold: 0 })}
          rows={exp.walkforward.param_history.map((r) => Object.values(r).map((v) => String(v)))}
        />
      </Panel>
      {selected ? (
        <>
          <Panel title={`Fold ${selected.index} — validation equity (${fmt.date(selected.validate[0])} → ${fmt.date(selected.validate[1])})`}>
            <LineChart series={selected.val_equity} height={180} />
            <div className="mt-2 grid grid-cols-2 gap-4 lg:grid-cols-4">
              <Stat label="train sharpe" value={fmt.signed(selected.train_metrics.sharpe)} />
              <Stat label="val sharpe" value={fmt.signed(selected.val_metrics.sharpe)} tone={(selected.val_metrics.sharpe ?? 0) >= 0 ? "gain" : "loss"} />
              <Stat label="val drawdown" value={fmt.pct(selected.val_metrics.max_drawdown)} />
              <Stat label="params" value={Object.entries(selected.best_params).map(([k, v]) => `${k}=${v}`).join(" ")} />
            </div>
          </Panel>
          <Panel title={`Fold ${selected.index} — every validation trade`}>
            <DataTable
              columns={["symbol", "side", "qty", "entry", "exit", "entry px", "exit px", "net pnl"]}
              rows={selected.val_trades.map((t) => [
                String(t.symbol),
                String(t.side),
                fmt.num(Number(t.qty), 0),
                fmt.time(String(t.entry_ts)),
                fmt.time(String(t.exit_ts)),
                fmt.num(Number(t.entry_price)),
                fmt.num(Number(t.exit_price)),
                <span key="p" className={Number(t.net_pnl) >= 0 ? "text-gain" : "text-loss"}>{fmt.signed(Number(t.net_pnl))}</span>,
              ])}
            />
          </Panel>
        </>
      ) : (
        <p className="text-sm text-ink-400">Select a fold above to inspect its validation equity and every trade.</p>
      )}
    </div>
  );
}

function Parameters({ exp }: { exp: Experiment }) {
  const heat = exp.sensitivity.heatmap;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="robustness" value={fmt.num(exp.sensitivity.robustness_score)} tone="amber" hint="sqrt(neighbor consistency × plateau fraction)" />
        <Stat label="neighbor consistency" value={fmt.num(exp.sensitivity.neighbor_consistency)} />
        <Stat label="plateau fraction" value={fmt.num(exp.sensitivity.plateau_fraction)} />
        <Stat label="combos tested" value={String(exp.sensitivity.n_combos)} />
      </div>
      {heat ? (
        <Panel title={`Parameter explorer — ${heat.y} × ${heat.x}, hover for detail`}>
          <Heatmap xLabel={heat.x} yLabel={heat.y} xValues={heat.x_values} yValues={heat.y_values} cells={heat.cells} objective={heat.objective} />
          <p className="mt-3 text-[11px] text-ink-400">
            Broad stable regions beat isolated peaks: a spike whose neighbors die is curve fitting wearing a good number.
          </p>
        </Panel>
      ) : (
        <p className="text-sm text-ink-400">Heatmap needs at least two swept parameters; this run varied fewer.</p>
      )}
    </div>
  );
}

function MonteCarlo({ exp }: { exp: Experiment }) {
  const mc = exp.montecarlo;
  const ciMethods = Object.keys(mc.cis);
  const metricRows = (method: string) => {
    const block = mc.cis[method] ?? {};
    return ["sharpe", "max_drawdown", "cagr", "profit_factor", "expectancy"]
      .filter((m) => block[m])
      .map((m) => [
        m.replace(/_/g, " "),
        fmt.num(block[m]["q0.025"]),
        fmt.num(block[m]["q0.5"]),
        fmt.num(block[m]["q0.975"]),
      ]);
  };
  return (
    <div className="space-y-4">
      {mc.fan ? (
        <>
          <Panel title={`${mc.fan.n_paths} reshuffled trade sequences (additive paths) — median, 5–95% and 25–75% bands, best and worst`}>
            <FanChart quantiles={mc.fan.quantiles} worst={mc.fan.worst_path} best={mc.fan.best_path} samples={mc.fan.sample_paths} />
          </Panel>
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Probability of ruin — P(max drawdown exceeds threshold)">
              <DataTable
                columns={["threshold", "probability"]}
                rows={Object.entries(mc.fan.prob_ruin).map(([t, p]) => [
                  fmt.pct(Number(t), 0),
                  <span key="p" className={p > 0.05 ? "text-loss" : "text-gain"}>{fmt.pct(p)}</span>,
                ])}
              />
            </Panel>
            {mc.delay_sweep && (
              <Panel title="Execution delay sweep (full engine re-runs)">
                <DataTable
                  columns={["delay (bars)", "sharpe", "max dd", "end equity"]}
                  rows={mc.delay_sweep.map((r) => [
                    String(r.delay_bars),
                    fmt.signed(r.sharpe),
                    fmt.pct(r.max_drawdown),
                    fmt.num(r.end_equity, 0),
                  ])}
                />
              </Panel>
            )}
          </div>
        </>
      ) : (
        <p className="text-sm text-ink-400">Not enough trades for Monte Carlo (needs ≥ 3).</p>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {ciMethods.map((method) => (
          <Panel key={method} title={`${method} — 95% confidence intervals`}>
            <DataTable columns={["metric", "q2.5", "median", "q97.5"]} rows={metricRows(method)} />
          </Panel>
        ))}
      </div>
      {mc.histograms && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Bootstrap end equity"><Histogram values={mc.histograms.end_equity} /></Panel>
          <Panel title="Bootstrap max drawdown"><Histogram values={mc.histograms.max_drawdown} format={(v) => fmt.pct(v)} /></Panel>
        </div>
      )}
    </div>
  );
}

function Regimes({ exp }: { exp: Experiment }) {
  const blocks = Object.entries(exp.regimes);
  if (blocks.length === 0) return <p className="text-sm text-ink-400">No regime data.</p>;
  return (
    <div className="space-y-4">
      <p className="text-[11px] text-ink-400">
        Regime labels are computed in-sample (median volatility split, trailing-return trend) — attribution, not a tradable signal.
      </p>
      <div className="grid gap-4 lg:grid-cols-3">
        {blocks.map(([name, table]) => (
          <Panel key={name} title={name.replace(/_/g, " ")}>
            <DataTable
              columns={["regime", "bars", "total", "sharpe"]}
              rows={Object.entries(table).map(([label, m]) => [
                label,
                fmt.num(m.n_bars, 0),
                <span key="t" className={m.total_return >= 0 ? "text-gain" : "text-loss"}>{fmt.pct(m.total_return)}</span>,
                fmt.signed(m.sharpe),
              ])}
            />
          </Panel>
        ))}
      </div>
    </div>
  );
}

function Report({ exp }: { exp: Experiment }) {
  const lines = useMemo(() => exp.report_markdown.split("\n"), [exp.report_markdown]);
  return (
    <div className="space-y-4">
      <div className="flex gap-3">
        <button onClick={() => api.downloadPdf(exp.id)} className="rounded border border-amber-signal px-3 py-1.5 text-xs uppercase tracking-widest text-amber-signal hover:bg-amber-signal hover:text-ink-950">
          Download PDF report
        </button>
        <Link href="/reports" className="rounded border border-ink-800 px-3 py-1.5 text-xs uppercase tracking-widest text-ink-400 hover:text-ink-100">
          All reports
        </Link>
      </div>
      <Panel title="Report (markdown source of the PDF)">
        <pre className="figure overflow-x-auto whitespace-pre-wrap text-xs leading-relaxed text-ink-100">
          {lines.join("\n")}
        </pre>
      </Panel>
    </div>
  );
}
