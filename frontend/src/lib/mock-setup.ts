/** Placeholder market data + AI setup scoring, shared by the Markets and
 * Scanner pages until real endpoints exist.
 *
 * TODO(backend): replace `buildCandles` with a real OHLC feed and
 * `buildSetup` with a real setup-scoring endpoint. Every caller only
 * depends on the `Candle`/`Setup` shapes below, so swapping the mock
 * generators for fetches is a localized change.
 */
import type { Candle } from "@/components/charts";

export const SCAN_UNIVERSE = [
  "AAPL", "MSFT", "NVDA", "TSLA", "SPY", "AMZN", "GOOGL", "META", "AMD", "NFLX",
  "JPM", "XOM", "COST", "DIS", "BA",
] as const;

export type Setup = {
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
export function buildCandles(symbol: string, n = 120): Candle[] {
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
export function buildSetup(symbol: string, candles: Candle[]): Setup {
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

export function riskReward(setup: Setup): number {
  const entry = (setup.buyZone[0] + setup.buyZone[1]) / 2;
  const risk = Math.abs(entry - setup.stopLoss);
  const reward = Math.abs(setup.profitTarget - entry);
  return risk === 0 ? 0 : reward / risk;
}
