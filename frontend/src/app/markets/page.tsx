"use client";
/** Markets: symbol chart + AI-generated trade setup.
 *
 * Price bars are real (fetched from Alpaca's market data via the
 * backend, api.marketBars) with a fallback to the placeholder generator
 * in @/lib/mock-setup if the fetch fails (e.g. no Alpaca keys configured
 * locally). Setup scoring (confidence/zone/stop/target) is still
 * placeholder either way — see the TODO(backend) note in mock-setup.ts.
 */
import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { Candle } from "@/components/charts";
import { CandlestickChart } from "@/components/charts";
import { ConfidenceStamp, Panel, Stat } from "@/components/ui";
import { api, fmt } from "@/lib/api";
import { SCAN_UNIVERSE, buildCandles, buildSetup, riskReward } from "@/lib/mock-setup";

function MarketsInner() {
  const params = useSearchParams();
  const fromQuery = params.get("symbol")?.toUpperCase();
  const initial =
    fromQuery && (SCAN_UNIVERSE as readonly string[]).includes(fromQuery) ? fromQuery : "AAPL";

  const [symbol, setSymbol] = useState<string>(initial);
  const [whyOpen, setWhyOpen] = useState(true);
  const [candles, setCandles] = useState<Candle[]>(() => buildCandles(initial));
  const [isLive, setIsLive] = useState(false);
  const [dataError, setDataError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDataError(null);
    api
      .marketBars(symbol)
      .then((bars) => {
        if (cancelled) return;
        setCandles(bars.map((b) => ({ t: b.t, o: b.o, h: b.h, l: b.l, c: b.c })));
        setIsLive(true);
      })
      .catch((e) => {
        if (cancelled) return;
        setCandles(buildCandles(symbol));
        setIsLive(false);
        setDataError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  const setup = useMemo(() => buildSetup(symbol, candles), [symbol, candles]);
  const rr = riskReward(setup);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg tracking-wide">Markets</h1>
            <span
              className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-widest ${
                isLive ? "border-gain text-gain" : "border-ink-800 text-ink-400"
              }`}
              title={dataError ?? undefined}
            >
              {isLive ? "live prices · alpaca" : "placeholder prices"}
            </span>
          </div>
          <p className="text-xs text-ink-400">
            AI setup scoring (confidence/zone/stop/target) is still placeholder — see TODOs in lib/mock-setup.ts.
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {SCAN_UNIVERSE.map((s) => (
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

export default function MarketsPage() {
  return (
    <Suspense fallback={null}>
      <MarketsInner />
    </Suspense>
  );
}
