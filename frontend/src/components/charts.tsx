"use client";
/** Chart kit — hand-rolled SVG, zero dependencies, deterministic.
 * Every figure renders exactly the numbers the pipeline stored. */

import { useMemo, useState } from "react";
import type { Fold, HeatCell, SeriesPoint } from "@/lib/api";
import { fmt } from "@/lib/api";

const GAIN = "var(--color-gain)";
const LOSS = "var(--color-loss)";
const AMBER = "var(--color-amber-signal)";
const MUTED = "var(--color-ink-400)";
const GRID = "#1a212c";

function scale(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

function extent(values: number[]): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!Number.isFinite(lo)) return [0, 1];
  return lo === hi ? [lo - 1, hi + 1] : [lo, hi];
}

function pathFrom(xs: number[], ys: number[]): string {
  let d = "";
  for (let i = 0; i < xs.length; i++) {
    d += `${i === 0 ? "M" : "L"}${xs[i].toFixed(1)},${ys[i].toFixed(1)}`;
  }
  return d;
}

/** Line chart over timestamped points; optional overlay series. */
export function LineChart({
  series,
  height = 220,
  color = AMBER,
  overlays = [],
  yFormat = (v: number) => fmt.num(v, 0),
  baseline,
}: {
  series: SeriesPoint[];
  height?: number;
  color?: string;
  overlays?: { points: SeriesPoint[]; color: string; label: string }[];
  yFormat?: (v: number) => string;
  baseline?: number;
}) {
  const width = 720;
  const pad = { l: 54, r: 8, t: 8, b: 20 };
  const [hover, setHover] = useState<number | null>(null);

  const values = series.map((p) => p[1]).filter((v): v is number => v !== null);
  const allValues = overlays.reduce(
    (acc, o) => acc.concat(o.points.map((p) => p[1]).filter((v): v is number => v !== null)),
    values.slice(),
  );
  const [lo, hi] = extent(allValues);
  const sx = scale([0, Math.max(series.length - 1, 1)], [pad.l, width - pad.r]);
  const sy = scale([lo, hi], [height - pad.b, pad.t]);

  const xs = series.map((_, i) => sx(i));
  const ys = series.map((p) => sy(p[1] ?? lo));
  const gridLines = 4;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
      role="img"
      onMouseLeave={() => setHover(null)}
      onMouseMove={(e) => {
        const rect = (e.target as SVGElement).closest("svg")!.getBoundingClientRect();
        const px = ((e.clientX - rect.left) / rect.width) * width;
        const i = Math.round(((px - pad.l) / (width - pad.l - pad.r)) * (series.length - 1));
        setHover(Math.max(0, Math.min(series.length - 1, i)));
      }}
    >
      {Array.from({ length: gridLines + 1 }, (_, k) => {
        const v = lo + ((hi - lo) * k) / gridLines;
        return (
          <g key={k}>
            <line x1={pad.l} x2={width - pad.r} y1={sy(v)} y2={sy(v)} stroke={GRID} strokeWidth={1} />
            <text x={pad.l - 6} y={sy(v) + 3} textAnchor="end" fontSize={10} fill={MUTED} className="figure">
              {yFormat(v)}
            </text>
          </g>
        );
      })}
      {baseline !== undefined && baseline >= lo && baseline <= hi && (
        <line x1={pad.l} x2={width - pad.r} y1={sy(baseline)} y2={sy(baseline)} stroke={MUTED} strokeDasharray="3 3" />
      )}
      {overlays.map((o) => {
        const oxs = o.points.map((_, i) => sx((i / Math.max(o.points.length - 1, 1)) * Math.max(series.length - 1, 1)));
        const oys = o.points.map((p) => sy(p[1] ?? lo));
        return <path key={o.label} d={pathFrom(oxs, oys)} fill="none" stroke={o.color} strokeWidth={1.4} opacity={0.9} />;
      })}
      <path d={pathFrom(xs, ys)} fill="none" stroke={color} strokeWidth={1.6} />
      {hover !== null && series[hover] && (
        <g>
          <line x1={xs[hover]} x2={xs[hover]} y1={pad.t} y2={height - pad.b} stroke={MUTED} strokeWidth={1} strokeDasharray="2 2" />
          <circle cx={xs[hover]} cy={ys[hover]} r={3} fill={color} />
          <text x={Math.min(xs[hover] + 6, width - 150)} y={pad.t + 12} fontSize={10} fill="var(--color-ink-100)" className="figure">
            {fmt.date(series[hover][0])} · {yFormat(series[hover][1] ?? 0)}
          </text>
        </g>
      )}
    </svg>
  );
}

/** Filled drawdown area (values ≤ 0). */
export function DrawdownChart({ series, height = 120 }: { series: SeriesPoint[]; height?: number }) {
  const width = 720;
  const pad = { l: 54, r: 8, t: 4, b: 16 };
  const values = series.map((p) => p[1] ?? 0);
  const [lo] = extent(values);
  const sx = scale([0, Math.max(series.length - 1, 1)], [pad.l, width - pad.r]);
  const sy = scale([Math.min(lo, -0.001), 0], [height - pad.b, pad.t]);
  const xs = series.map((_, i) => sx(i));
  const ys = values.map((v) => sy(v));
  const area = `${pathFrom(xs, ys)}L${xs[xs.length - 1]},${sy(0)}L${xs[0]},${sy(0)}Z`;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img">
      <line x1={pad.l} x2={width - pad.r} y1={sy(0)} y2={sy(0)} stroke={GRID} />
      <text x={pad.l - 6} y={sy(lo) + 3} textAnchor="end" fontSize={10} fill={MUTED} className="figure">
        {fmt.pct(lo)}
      </text>
      <path d={area} fill={LOSS} opacity={0.45} stroke={LOSS} strokeWidth={1} />
    </svg>
  );
}

/** Monte Carlo fan: quantile bands + best/worst + sample spaghetti. */
export function FanChart({
  quantiles,
  worst,
  best,
  samples,
  height = 260,
}: {
  quantiles: Record<string, number[]>;
  worst: number[];
  best: number[];
  samples: number[][];
  height?: number;
}) {
  const width = 720;
  const pad = { l: 60, r: 8, t: 8, b: 18 };
  const steps = quantiles["0.5"].length;
  const all = [...worst, ...best];
  const [lo, hi] = extent(all);
  const sx = scale([0, steps - 1], [pad.l, width - pad.r]);
  const sy = scale([lo, hi], [height - pad.b, pad.t]);
  const line = (v: number[]) => pathFrom(v.map((_, i) => sx(i)), v.map((y) => sy(y)));
  const band = (upper: number[], lower: number[]) => {
    const up = upper.map((y, i) => `${i === 0 ? "M" : "L"}${sx(i).toFixed(1)},${sy(y).toFixed(1)}`).join("");
    const down = lower
      .slice()
      .reverse()
      .map((y, i) => `L${sx(lower.length - 1 - i).toFixed(1)},${sy(y).toFixed(1)}`)
      .join("");
    return `${up}${down}Z`;
  };
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img">
      {[lo, (lo + hi) / 2, hi].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={width - pad.r} y1={sy(v)} y2={sy(v)} stroke={GRID} />
          <text x={pad.l - 6} y={sy(v) + 3} textAnchor="end" fontSize={10} fill={MUTED} className="figure">
            {fmt.num(v, 0)}
          </text>
        </g>
      ))}
      {samples.map((path, i) => (
        <path key={i} d={line(path)} fill="none" stroke={MUTED} strokeWidth={0.5} opacity={0.22} />
      ))}
      <path d={band(quantiles["0.95"], quantiles["0.05"])} fill={AMBER} opacity={0.14} />
      <path d={band(quantiles["0.75"], quantiles["0.25"])} fill={AMBER} opacity={0.22} />
      <path d={line(quantiles["0.5"])} fill="none" stroke={AMBER} strokeWidth={1.8} />
      <path d={line(worst)} fill="none" stroke={LOSS} strokeWidth={1.2} strokeDasharray="4 3" />
      <path d={line(best)} fill="none" stroke={GAIN} strokeWidth={1.2} strokeDasharray="4 3" />
    </svg>
  );
}

/** Parameter heatmap with hover detail: the Parameter Explorer core. */
export function Heatmap({
  xLabel,
  yLabel,
  xValues,
  yValues,
  cells,
  objective,
}: {
  xLabel: string;
  yLabel: string;
  xValues: number[];
  yValues: number[];
  cells: HeatCell[];
  objective: string;
}) {
  const [hover, setHover] = useState<HeatCell | null>(null);
  const lookup = useMemo(() => {
    const m = new Map<string, HeatCell>();
    for (const c of cells) m.set(`${c.x}|${c.y}`, c);
    return m;
  }, [cells]);
  const values = cells.map((c) => c.sharpe).filter((v): v is number => v !== null);
  const [lo, hi] = extent(values);
  const colorFor = (v: number | null) => {
    if (v === null) return "#141a24";
    const t = (v - lo) / (hi - lo || 1);
    // loss red -> ink -> gain green through the terminal palette
    const mix = (a: number, b: number) => Math.round(a + (b - a) * t);
    return `rgb(${mix(178, 53)}, ${mix(58, 196)}, ${mix(74, 141)})`;
  };
  const cell = 54;
  const padL = 64;
  const padT = 10;
  const width = padL + xValues.length * cell + 10;
  const heatH = padT + yValues.length * cell + 30;
  return (
    <div className="flex flex-wrap items-start gap-4">
      <svg viewBox={`0 0 ${width} ${heatH}`} style={{ width: Math.min(width, 560) }} role="img">
        {yValues.map((y, j) => (
          <text key={y} x={padL - 8} y={padT + (yValues.length - 1 - j) * cell + cell / 2 + 4} textAnchor="end" fontSize={11} fill={MUTED} className="figure">
            {y}
          </text>
        ))}
        {xValues.map((x, i) => (
          <text key={x} x={padL + i * cell + cell / 2} y={padT + yValues.length * cell + 16} textAnchor="middle" fontSize={11} fill={MUTED} className="figure">
            {x}
          </text>
        ))}
        {yValues.map((y, j) =>
          xValues.map((x, i) => {
            const c = lookup.get(`${x}|${y}`) ?? null;
            const v = c?.sharpe ?? null;
            return (
              <g key={`${x}|${y}`}>
                <rect
                  x={padL + i * cell + 1}
                  y={padT + (yValues.length - 1 - j) * cell + 1}
                  width={cell - 2}
                  height={cell - 2}
                  rx={3}
                  fill={colorFor(v)}
                  stroke={hover === c ? AMBER : "transparent"}
                  strokeWidth={2}
                  onMouseEnter={() => setHover(c)}
                  onMouseLeave={() => setHover(null)}
                  style={{ cursor: "crosshair" }}
                />
                <text
                  x={padL + i * cell + cell / 2}
                  y={padT + (yValues.length - 1 - j) * cell + cell / 2 + 4}
                  textAnchor="middle"
                  fontSize={11}
                  fill="#0a0e14"
                  className="figure pointer-events-none"
                  fontWeight={600}
                >
                  {v === null ? "·" : v.toFixed(2)}
                </text>
              </g>
            );
          }),
        )}
        <text x={padL + (xValues.length * cell) / 2} y={heatH - 2} textAnchor="middle" fontSize={11} fill={MUTED}>
          {xLabel}
        </text>
        <text x={12} y={padT + (yValues.length * cell) / 2} fontSize={11} fill={MUTED} transform={`rotate(-90 12 ${padT + (yValues.length * cell) / 2})`} textAnchor="middle">
          {yLabel}
        </text>
      </svg>
      <div className="min-w-52 rounded border border-ink-800 bg-ink-900 p-3 text-sm">
        <div className="mb-2 text-xs uppercase tracking-wider text-ink-400">
          {hover ? `${xLabel}=${hover.x} · ${yLabel}=${hover.y}` : "hover a cell"}
        </div>
        {(
          [
            ["sharpe", fmt.signed(hover?.sharpe)],
            ["drawdown", fmt.pct(hover?.max_drawdown)],
            ["profit factor", fmt.num(hover?.profit_factor)],
            ["win rate", fmt.pct(hover?.win_rate)],
            ["trades", fmt.num(hover?.n_trades, 0)],
          ] as const
        ).map(([k, v]) => (
          <div key={k} className="flex justify-between gap-6 border-b border-ink-800 py-1 last:border-0">
            <span className="text-ink-400">{k}</span>
            <span className="figure">{v}</span>
          </div>
        ))}
        <div className="mt-2 text-[10px] text-ink-400">cell color = {objective}</div>
      </div>
    </div>
  );
}

/** Histogram for trade P&L / MC end-equity distributions. */
export function Histogram({
  values,
  bins = 24,
  height = 150,
  format = (v: number) => fmt.num(v, 0),
  zeroSplit = false,
}: {
  values: number[];
  bins?: number;
  height?: number;
  format?: (v: number) => string;
  zeroSplit?: boolean;
}) {
  const width = 720;
  const pad = { l: 10, r: 10, t: 6, b: 18 };
  const [lo, hi] = extent(values);
  const counts = new Array(bins).fill(0);
  for (const v of values) {
    const i = Math.min(bins - 1, Math.floor(((v - lo) / (hi - lo || 1)) * bins));
    counts[i]++;
  }
  const maxCount = Math.max(...counts, 1);
  const bw = (width - pad.l - pad.r) / bins;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img">
      {counts.map((c, i) => {
        const mid = lo + ((i + 0.5) / bins) * (hi - lo);
        const barH = ((height - pad.t - pad.b) * c) / maxCount;
        const color = zeroSplit ? (mid >= 0 ? GAIN : LOSS) : AMBER;
        return (
          <rect key={i} x={pad.l + i * bw + 1} y={height - pad.b - barH} width={bw - 2} height={barH} fill={color} opacity={0.75} rx={1} />
        );
      })}
      <text x={pad.l} y={height - 4} fontSize={10} fill={MUTED} className="figure">{format(lo)}</text>
      <text x={width - pad.r} y={height - 4} fontSize={10} fill={MUTED} textAnchor="end" className="figure">{format(hi)}</text>
    </svg>
  );
}

/** Calendar of monthly returns. */
export function MonthlyGrid({ rows }: { rows: { year: number; month: number; value: number | null }[] }) {
  const years = [...new Set(rows.map((r) => r.year))].sort();
  const byKey = new Map(rows.map((r) => [`${r.year}-${r.month}`, r.value]));
  const months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
  return (
    <div className="overflow-x-auto">
      <table className="figure text-xs">
        <thead>
          <tr>
            <th className="pr-3 text-left font-normal text-ink-400">year</th>
            {months.map((m, i) => (
              <th key={i} className="w-14 pb-1 text-center font-normal text-ink-400">{m}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {years.map((y) => (
            <tr key={y}>
              <td className="pr-3 text-ink-400">{y}</td>
              {months.map((_, i) => {
                const v = byKey.get(`${y}-${i + 1}`);
                const bg = v == null ? "transparent" : v >= 0 ? "rgba(53,196,141,0.22)" : "rgba(227,93,106,0.25)";
                const color = v == null ? "var(--color-ink-400)" : v >= 0 ? GAIN : LOSS;
                return (
                  <td key={i} className="p-0.5 text-center">
                    <div className="rounded px-1 py-1.5" style={{ background: bg, color }}>
                      {v == null ? "·" : fmt.pct(v, 1)}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** OHLC candlestick chart with optional buy-zone / stop / target overlays —
 * the "TradingView-style" price panel for the Markets page. */
export type Candle = { t: string; o: number; h: number; l: number; c: number };

export function CandlestickChart({
  candles,
  height = 360,
  buyZone,
  stopLoss,
  profitTarget,
}: {
  candles: Candle[];
  height?: number;
  buyZone?: [number, number];
  stopLoss?: number;
  profitTarget?: number;
}) {
  const width = 900;
  const pad = { l: 56, r: 8, t: 10, b: 22 };
  const [hover, setHover] = useState<number | null>(null);

  const highs = candles.map((c) => c.h);
  const lows = candles.map((c) => c.l);
  const levels = [stopLoss, profitTarget, buyZone?.[0], buyZone?.[1]].filter(
    (v): v is number => v !== undefined,
  );
  const [lo, hi] = extent([...highs, ...lows, ...levels]);
  const sx = scale([0, Math.max(candles.length - 1, 1)], [pad.l, width - pad.r]);
  const sy = scale([lo, hi], [height - pad.b, pad.t]);
  const bw = Math.max(((width - pad.l - pad.r) / candles.length) * 0.6, 1);
  const gridLines = 4;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
      role="img"
      onMouseLeave={() => setHover(null)}
      onMouseMove={(e) => {
        const rect = (e.target as SVGElement).closest("svg")!.getBoundingClientRect();
        const px = ((e.clientX - rect.left) / rect.width) * width;
        const i = Math.round(((px - pad.l) / (width - pad.l - pad.r)) * (candles.length - 1));
        setHover(Math.max(0, Math.min(candles.length - 1, i)));
      }}
    >
      {Array.from({ length: gridLines + 1 }, (_, k) => {
        const v = lo + ((hi - lo) * k) / gridLines;
        return (
          <g key={k}>
            <line x1={pad.l} x2={width - pad.r} y1={sy(v)} y2={sy(v)} stroke={GRID} strokeWidth={1} />
            <text x={pad.l - 6} y={sy(v) + 3} textAnchor="end" fontSize={10} fill={MUTED} className="figure">
              {fmt.num(v, 2)}
            </text>
          </g>
        );
      })}
      {buyZone && (
        <rect
          x={pad.l}
          y={sy(buyZone[1])}
          width={width - pad.l - pad.r}
          height={Math.max(sy(buyZone[0]) - sy(buyZone[1]), 1)}
          fill={AMBER}
          opacity={0.1}
        />
      )}
      {stopLoss !== undefined && (
        <line x1={pad.l} x2={width - pad.r} y1={sy(stopLoss)} y2={sy(stopLoss)} stroke={LOSS} strokeWidth={1.2} strokeDasharray="4 3" />
      )}
      {profitTarget !== undefined && (
        <line x1={pad.l} x2={width - pad.r} y1={sy(profitTarget)} y2={sy(profitTarget)} stroke={GAIN} strokeWidth={1.2} strokeDasharray="4 3" />
      )}
      {candles.map((c, i) => {
        const x = sx(i);
        const up = c.c >= c.o;
        const color = up ? GAIN : LOSS;
        const bodyTop = sy(Math.max(c.o, c.c));
        const bodyBot = sy(Math.min(c.o, c.c));
        return (
          <g key={c.t} opacity={hover === null || hover === i ? 1 : 0.55}>
            <line x1={x} x2={x} y1={sy(c.h)} y2={sy(c.l)} stroke={color} strokeWidth={1} />
            <rect
              x={x - bw / 2}
              y={bodyTop}
              width={bw}
              height={Math.max(bodyBot - bodyTop, 1)}
              fill={color}
            />
          </g>
        );
      })}
      {hover !== null && candles[hover] && (
        <g>
          <line x1={sx(hover)} x2={sx(hover)} y1={pad.t} y2={height - pad.b} stroke={MUTED} strokeWidth={1} strokeDasharray="2 2" />
          <text x={Math.min(sx(hover) + 6, width - 190)} y={pad.t + 12} fontSize={10} fill="var(--color-ink-100)" className="figure">
            {fmt.date(candles[hover].t)} · O {fmt.num(candles[hover].o, 2)} H {fmt.num(candles[hover].h, 2)} L{" "}
            {fmt.num(candles[hover].l, 2)} C {fmt.num(candles[hover].c, 2)}
          </text>
        </g>
      )}
    </svg>
  );
}

/** Walk-forward fold timeline: the signature element. Train bars in ink,
 * validation in amber; the reserved holdout burns red at the end. */
export function FoldTimeline({
  folds,
  workRange,
  holdoutRange,
  selected,
  onSelect,
}: {
  folds: Fold[];
  workRange: [string, string];
  holdoutRange: [string, string];
  selected: number | null;
  onSelect: (i: number) => void;
}) {
  const t0 = new Date(workRange[0]).getTime();
  const t1 = new Date(holdoutRange[1]).getTime();
  const sx = scale([t0, t1], [0, 100]);
  const pos = (iso: string) => sx(new Date(iso).getTime());
  const rowH = 26;
  return (
    <div className="space-y-1">
      {folds.map((f) => (
        <button
          key={f.index}
          onClick={() => onSelect(f.index)}
          className={`relative block h-[26px] w-full rounded border text-left transition-colors ${
            selected === f.index ? "border-amber-signal bg-ink-800" : "border-ink-800 bg-ink-900 hover:border-ink-400"
          }`}
          style={{ height: rowH }}
          aria-label={`fold ${f.index}`}
        >
          <span
            className="absolute top-[5px] h-4 rounded-sm bg-ink-400/40"
            style={{ left: `${pos(f.train[0])}%`, width: `${Math.max(pos(f.train[1]) - pos(f.train[0]), 1)}%` }}
          />
          <span
            className="absolute top-[5px] h-4 rounded-sm"
            style={{
              left: `${pos(f.validate[0])}%`,
              width: `${Math.max(pos(f.validate[1]) - pos(f.validate[0]), 1)}%`,
              background: AMBER,
            }}
          />
          <span className="figure absolute left-1 top-[5px] text-[10px] text-ink-400">
            {f.index}
          </span>
          <span className="figure absolute right-1 top-[5px] text-[10px]" style={{ color: (f.val_metrics.sharpe ?? 0) >= 0 ? GAIN : LOSS }}>
            val {fmt.signed(f.val_metrics.sharpe)}
          </span>
        </button>
      ))}
      <div className="relative h-[26px] w-full rounded border border-loss/50 bg-ink-900">
        <span
          className="absolute top-[5px] h-4 rounded-sm bg-loss/35"
          style={{ left: `${pos(holdoutRange[0])}%`, width: `${Math.max(pos(holdoutRange[1]) - pos(holdoutRange[0]), 1)}%` }}
        />
        <span className="figure absolute left-1 top-[5px] text-[10px] text-loss">
          holdout — evaluated once
        </span>
      </div>
      <div className="flex gap-4 pt-1 text-[10px] text-ink-400">
        <span><span className="mr-1 inline-block h-2 w-4 rounded-sm bg-ink-400/40 align-middle" />train</span>
        <span><span className="mr-1 inline-block h-2 w-4 rounded-sm align-middle" style={{ background: AMBER }} />validate</span>
        <span><span className="mr-1 inline-block h-2 w-4 rounded-sm bg-loss/35 align-middle" />final test</span>
      </div>
    </div>
  );
}
