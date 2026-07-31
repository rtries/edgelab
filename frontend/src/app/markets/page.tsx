"use client";
/** Markets: symbol chart + AI-generated trade setup.
 *
 * TODO(backend): everything under `buildSetup()` below is placeholder —
 * there is no live-data or setup-scoring endpoint yet. Once one exists
 * (candles + confidence/zone/stop/target from a real model), swap
 * `buildSetup(symbol)` for a fetch to it and delete the mock generator.
 * The layout, chart, and sidebar are already wired for real data: they
 * only care about the `Candle[]` and `Setup` shapes below.
 */
import { useMemo, useState } from "react";
import { CandlestickChart, type Candle } from "@/components/charts";
import { ConfidenceStamp, Panel, Stat } from "@/components/ui";
import { fmt } from "@/lib/api";

const SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY"] as const;

type Setup = {
  confidence: number; // 0..1
  confidenceLevel: "strong" | "moderate" | "weak" | "insufficient";
  bias: "long" | "short";
  buyZone: [number, number];
  stopLoss: number;
  profitTarget: number;
  reasons: string[];
};

// Deterministic PRNG so a given symbol always renders the same mock
// chart/setup within a session — no backend, no randomness on refresh.
function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function seedFromSymbol(symbol: string): number {
  let h = 0;
  for (let i = 0; i < symbol.length; i++) h = (h * 31 + symbol.charCodeAt(i)) | 0;
  return h;
}

// TODO(backend): replace with a real OHLC feed for `symbol`.
function buildCandles(symbol: string, n = 120): Candle[] {
  const rng = mulberry32(seedFromSymbol(symbol));
  const candles: Candle[] = [];
  let price = 80 + rng() * 240;
  const start = new Date();
  start.setDate(start.getDate() - n);
  for (let i = 0; i < n; i++) {
    const drift = (rng() - 0.48) * 0.02;
    const open = price;
    const close = Math.max(1, open * (1 + drift));
    const high = Math.max(open, close) * (1 + rng() * 0.012);
    const low = Math.min(open, close) * (1 - rng() * 0.012);
    const t = new Date(start);
    t.setDate(t.getDate() + i);
    candles.push({ t: t.toISOString(), o: open, h: high, l: low, c: close });
    price = close;
  }
  return candles;
}

// TODO(backend): replace with a real setup-scoring endpoint response.
function buildSetup(symbol: string, candles: Candle[]): Setup {
  const rng = mulberry32(seedFromSymbol(symbol) ^ 0x9e3779b9);
  const last = candles[candles.length - 1].c;
  const confidence = 0.35 + rng() * 0.6;
  const confidenceLevel: Setup["confidenceLevel"] =
    confidence >= 0.75 ? "strong" : confidence >= 0.55 ? "moderate" : confidence >= 0.4 ? "weak" : "insufficient";
  const bias: Setup["bias"] = rng() > 0.3 ? "long" : "short";
  const zoneWidth = last * 0.015;
  const buyZone: [number, number] = [last - zoneWidth, last - zoneWidth * 0.2];
  const stopLoss = bias === "long" ? buyZone[0] * 0.97 : buyZone[1] * 1.03;
  const risk = Math.abs(buyZone[0] - stopLoss);
  const profitTarget = bias === "long" ? buyZone[1] + risk * 2.2 : buyZone[0] - risk * 2.2;
  return {
    confidence,
    confidenceLevel,
    bias,
    buyZone,
    stopLoss,
    profitTarget,
    reasons: [
      `Price is consolidating near its ${bias === "long" ? "20-period support" : "20-period resistance"} band, the kind of area this model weighs as a higher-probability entry.`,
      `Recent volatility is ${rng() > 0.5 ? "contracting" : "elevated"}, which shapes how wide the suggested stop needs to be to avoid noise.`,
      `Momentum over the last 10 bars is ${bias === "long" ? "turning up" : "turning down"}, agreeing with the suggested direction — not a guarantee, one input among several.`,
      "This is a probability read on historical pattern behavior, not a prediction. Position size for the stop distance, not the target.",
    ],
  };
}

function riskReward(setup: Setup): number {
  const entry = (setup.buyZone[0] + setup.buyZone[1]) / 2;
  const risk = Math.abs(entry - setup.stopLoss);
  const reward = Math.abs(setup.profitTarget - entry);
  return risk === 0 ? 0 : reward / risk;
}

export default function MarketsPage() {
  const [symbol, setSymbol] = useState<(typeof SYMBOLS)[number]>("AAPL");
  const [whyOpen, setWhyOpen] = useState(true);

  const candles = useMemo(() => buildCandles(symbol), [symbol]);
  const setup = useMemo(() => buildSetup(symbol, candles), [symbol, candles]);
  const rr = riskReward(setup);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg tracking-wide">Markets</h1>
          <p className="text-xs text-ink-400">
            Placeholder price data and AI setup scoring — see TODOs in this page for the real endpoints to wire up.
          </p>
        </div>
        <div className="flex gap-1">
          {SYMBOLS.map((s) => (
            <button
              key={s}
              onClick={() => setSymbol(s)}
              className={`figure rounded border px-3 py-1.5 text-xs uppercase tracking-widest transition-colors ${
                symbol === s
                  ? "border-amber-signal text-amber-signal"
                  : "border-ink-800 text-ink-400 hover:border-ink-400 hover:text-ink-100"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_280px]">
        <div className="space-y-4">
          <Panel
            title={`${symbol} · 1D`}
            right={<span className="figure text-sm text-ink-100">{fmt.num(candles[candles.length - 1].c, 2)}</span>}
          >
            <CandlestickChart
              candles={candles}
              buyZone={setup.buyZone}
              stopLoss={setup.stopLoss}
              profitTarget={setup.profitTarget}
              height={420}
            />
            <div className="mt-2 flex flex-wrap gap-4 text-[10px] text-ink-400">
              <span><span className="mr-1 inline-block h-2 w-4 rounded-sm bg-amber-signal/20 align-middle" />suggested buy zone</span>
              <span><span className="mr-1 inline-block h-0.5 w-4 bg-loss align-middle" />stop loss</span>
              <span><span className="mr-1 inline-block h-0.5 w-4 bg-gain align-middle" />profit target</span>
            </div>
          </Panel>

          <Panel title="Why this setup?" right={
            <button
              onClick={() => setWhyOpen((v) => !v)}
              className="text-[10px] uppercase tracking-widest text-ink-400 hover:text-amber-signal"
            >
              {whyOpen ? "collapse" : "expand"}
            </button>
          }>
            {whyOpen ? (
              <ul className="space-y-2 text-sm leading-relaxed text-ink-100">
                {setup.reasons.map((r, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-amber-signal">·</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-ink-400">Explanation collapsed — click expand to read the reasoning behind this setup.</p>
            )}
          </Panel>
        </div>

        <div className="space-y-4">
          <Panel title="AI Setup">
            <div className="space-y-3">
              <div>
                <div className="mb-1 text-[10px] uppercase tracking-widest text-ink-400">confidence score</div>
                <div className="flex items-center gap-2">
                  <ConfidenceStamp level={setup.confidenceLevel} />
                  <span className="figure text-sm text-ink-100">{fmt.pct(setup.confidence, 0)}</span>
                </div>
              </div>
              <Stat
                label={`bias: ${setup.bias}`}
                value=""
                tone={setup.bias === "long" ? "gain" : "loss"}
              />
              <div className="grid grid-cols-2 gap-3 border-t border-ink-800 pt-3">
                <Stat label="buy zone low" value={fmt.num(setup.buyZone[0], 2)} />
                <Stat label="buy zone high" value={fmt.num(setup.buyZone[1], 2)} />
                <Stat label="stop loss" value={fmt.num(setup.stopLoss, 2)} tone="loss" />
                <Stat label="profit target" value={fmt.num(setup.profitTarget, 2)} tone="gain" />
              </div>
              <div className="border-t border-ink-800 pt-3">
                <Stat label="risk / reward" value={`1 : ${rr.toFixed(2)}`} tone={rr >= 1.5 ? "gain" : "amber"} />
              </div>
              <p className="border-t border-ink-800 pt-3 text-[10px] leading-relaxed text-ink-400">
                Probability-based analysis, not a prediction or a guarantee of profit. Confidence score reflects
                historical pattern agreement, not certainty of outcome.
              </p>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
