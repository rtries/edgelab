"use client";
/** Stock research page: chart + AI setup + company research — the page
 * every symbol (from search, Scanner, or a watchlist) lands on.
 *
 * Price/volume bars are real (Alpaca via api.marketBars), with a
 * placeholder fallback if the fetch fails. AI setup scoring and every
 * card on the Research tab are placeholder — see TODO(backend) notes
 * inline and in @/lib/mock-setup. Nothing here fabricates real facts
 * about the company (market cap, news, ratings): where there's no real
 * data source yet, the UI says so instead of making a number up.
 */
import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import type { Candle } from "@/components/charts";
import { CandlestickChart, VolumeChart } from "@/components/charts";
import { ConfidenceStamp, Panel, PreviewBadge, Stat, Tabs } from "@/components/ui";
import { api, fmt } from "@/lib/api";
import { buildCandles, buildSetup, riskReward } from "@/lib/mock-setup";
import { SymbolSearch } from "@/components/symbol-search";

const TIMEFRAMES: { label: string; timeframe: string; limit: number }[] = [
  { label: "1M", timeframe: "1Day", limit: 22 },
  { label: "3M", timeframe: "1Day", limit: 65 },
  { label: "6M", timeframe: "1Day", limit: 130 },
  { label: "1Y", timeframe: "1Day", limit: 260 },
  { label: "5Y", timeframe: "1Week", limit: 260 },
];

const TABS = ["Overview", "Research"];

// TODO(backend): every field here needs a real fundamentals/reference-data
// provider. Deliberately shown as "not available yet" rather than a made-up
// number — faking a real company's market cap would be actively misleading,
// unlike the clearly-labeled synthetic price/AI-setup placeholders elsewhere.
const RESEARCH_CARDS = [
  { title: "Company overview", note: "Business description, sector, employees, headquarters." },
  { title: "Recent news", note: "Headlines relevant to this symbol." },
  { title: "Analyst ratings", note: "Buy/hold/sell consensus and price targets." },
  { title: "Earnings", note: "Upcoming date, EPS estimate vs. actual history." },
  { title: "Insider transactions", note: "Recent buys/sells by company insiders." },
  { title: "Institutional ownership", note: "% held by funds, recent 13F changes." },
  { title: "Sector performance", note: "How this symbol's sector is trading today." },
  { title: "Options activity", note: "Unusual volume, put/call ratio." },
];

export default function StockPage() {
  const { symbol: rawSymbol } = useParams<{ symbol: string }>();
  const symbol = decodeURIComponent(rawSymbol).toUpperCase();
  const router = useRouter();

  const [tab, setTab] = useState("Overview");
  const [whyOpen, setWhyOpen] = useState(true);
  const [range, setRange] = useState(TIMEFRAMES[3]); // 1Y default
  const [candles, setCandles] = useState<Candle[]>(() => buildCandles(symbol));
  const [isLive, setIsLive] = useState(false);
  const [dataError, setDataError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setDataError(null);
    api
      .marketBars(symbol, range.timeframe, range.limit)
      .then((bars) => {
        if (cancelled) return;
        setCandles(bars.map((b) => ({ t: b.t, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v })));
        setIsLive(true);
      })
      .catch((e) => {
        if (cancelled) return;
        setCandles(buildCandles(symbol, range.limit));
        setIsLive(false);
        setDataError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, range]);

  const setup = useMemo(() => buildSetup(symbol, candles), [symbol, candles]);
  const rr = riskReward(setup);

  const last = candles[candles.length - 1];
  const prev = candles[candles.length - 2] ?? last;
  const change = last.c - prev.c;
  const changePct = prev.c === 0 ? 0 : change / prev.c;
  const dayHigh = last.h;
  const dayLow = last.l;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl tracking-wide">{symbol}</h1>
            <span
              className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-widest ${
                isLive ? "border-gain text-gain" : "border-ink-800 text-ink-400"
              }`}
              title={dataError ?? undefined}
            >
              {isLive ? "live · alpaca" : "placeholder"}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap items-baseline gap-3">
            <span className="figure text-2xl text-ink-100">{fmt.num(last.c, 2)}</span>
            <span className={`figure text-sm ${change >= 0 ? "text-gain" : "text-loss"}`}>
              {change >= 0 ? "+" : ""}
              {fmt.num(change, 2)} ({fmt.pct(changePct, 2)})
            </span>
          </div>
          <div className="mt-1 flex flex-wrap gap-4 text-xs text-ink-400">
            <span>day range <span className="figure text-ink-100">{fmt.num(dayLow, 2)}–{fmt.num(dayHigh, 2)}</span></span>
            <span title="TODO(backend): needs a fundamentals/reference-data provider">
              market cap <span className="figure">— not available yet</span>
            </span>
          </div>
        </div>
        <div className="w-64">
          <SymbolSearch onSelect={(s) => router.push(`/stock/${s}`)} placeholder="search another symbol…" />
        </div>
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === "Overview" ? (
        <div className="grid gap-4 xl:grid-cols-[1fr_280px]">
          <div className="space-y-4">
            <Panel
              title={`${symbol} · ${range.label}`}
              right={
                <div className="flex gap-1">
                  {TIMEFRAMES.map((tf) => (
                    <button
                      key={tf.label}
                      onClick={() => setRange(tf)}
                      className={`rounded border px-2 py-0.5 text-[10px] uppercase tracking-widest transition-colors ${
                        range.label === tf.label
                          ? "border-amber-signal text-amber-signal"
                          : "border-ink-800 text-ink-400 hover:border-ink-400 hover:text-ink-100"
                      }`}
                    >
                      {tf.label}
                    </button>
                  ))}
                </div>
              }
            >
              {loading ? (
                <div className="figure animate-pulse py-16 text-center text-sm text-ink-400">loading chart…</div>
              ) : (
                <>
                  <CandlestickChart
                    candles={candles}
                    buyZone={setup.buyZone}
                    stopLoss={setup.stopLoss}
                    profitTarget={setup.profitTarget}
                    height={400}
                  />
                  <VolumeChart candles={candles} height={70} />
                  <div className="mt-2 flex flex-wrap gap-4 text-[10px] text-ink-400">
                    <span><span className="mr-1 inline-block h-2 w-4 rounded-sm bg-amber-signal/20 align-middle" />suggested buy zone</span>
                    <span><span className="mr-1 inline-block h-0.5 w-4 bg-loss align-middle" />stop loss</span>
                    <span><span className="mr-1 inline-block h-0.5 w-4 bg-gain align-middle" />profit target</span>
                  </div>
                </>
              )}
            </Panel>

            <Panel
              title="Why this setup?"
              right={
                <div className="flex items-center gap-2">
                  <PreviewBadge />
                  <button
                    onClick={() => setWhyOpen((v) => !v)}
                    className="text-[10px] uppercase tracking-widest text-ink-400 hover:text-amber-signal"
                  >
                    {whyOpen ? "collapse" : "expand"}
                  </button>
                </div>
              }
            >
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
            <Panel title="AI Setup" right={<PreviewBadge />}>
              <div className="space-y-3">
                <div>
                  <div className="mb-1 text-[10px] uppercase tracking-widest text-ink-400">
                    current trend · ai confidence
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`figure text-sm ${setup.bias === "long" ? "text-gain" : "text-loss"}`}>
                      {setup.bias === "long" ? "Bullish" : "Bearish"}
                    </span>
                    <ConfidenceStamp level={setup.confidenceLevel} />
                    <span className="figure text-sm text-ink-100">{fmt.pct(setup.confidence, 0)}</span>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3 border-t border-ink-800 pt-3">
                  <Stat label="entry zone low" value={fmt.num(setup.buyZone[0], 2)} />
                  <Stat label="entry zone high" value={fmt.num(setup.buyZone[1], 2)} />
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
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {RESEARCH_CARDS.map((card) => (
            <Panel key={card.title} title={card.title}>
              <p className="text-xs leading-relaxed text-ink-400">{card.note}</p>
              <p className="mt-3 rounded border border-ink-800 bg-ink-950 px-2 py-1.5 text-[10px] uppercase tracking-widest text-ink-400">
                not connected yet — TODO(backend)
              </p>
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
