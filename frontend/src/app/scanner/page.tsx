"use client";
/** Scanner: runs the AI setup scoring across a symbol universe and ranks
 * by confidence — "find me the best setups right now."
 *
 * Prices are real (fetched once per symbol from Alpaca via
 * api.marketBars, per-symbol fallback to placeholder on failure). The
 * setup scoring layered on top re-runs every 30s but is still
 * placeholder — see @/lib/mock-setup TODOs. SCAN_UNIVERSE itself is
 * still a hardcoded 15-symbol list.
 *
 * TODO(backend): replace SCAN_UNIVERSE with the user's real watchlist
 * or a broader screenable universe once a screening endpoint exists.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { Candle } from "@/components/charts";
import { ConfidenceStamp, Panel, PreviewBadge } from "@/components/ui";
import { api, fmt } from "@/lib/api";
import { SCAN_UNIVERSE, buildCandles, buildSetup, riskReward, type Setup } from "@/lib/mock-setup";

const RESCAN_INTERVAL_MS = 30_000;

type Row = {
  symbol: string;
  price: number;
  isLive: boolean;
  setup: Setup;
  rr: number;
};

type SortKey = "confidence" | "rr" | "symbol";

export default function ScannerPage() {
  const [biasFilter, setBiasFilter] = useState<"all" | "long" | "short">("all");
  const [sortKey, setSortKey] = useState<SortKey>("confidence");
  const [nonce, setNonce] = useState(0);
  const [lastScanned, setLastScanned] = useState<Date | null>(null);
  const [candlesBySymbol, setCandlesBySymbol] = useState<Record<string, Candle[]>>({});
  const [liveBySymbol, setLiveBySymbol] = useState<Record<string, boolean>>({});
  const [loadingPrices, setLoadingPrices] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoadingPrices(true);
    Promise.all(
      SCAN_UNIVERSE.map((symbol) =>
        api
          .marketBars(symbol)
          .then((bars) => ({
            symbol,
            live: true,
            candles: bars.map((b) => ({ t: b.t, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v })),
          }))
          .catch(() => ({ symbol, live: false, candles: buildCandles(symbol) })),
      ),
    ).then((results) => {
      if (cancelled) return;
      const candles: Record<string, Candle[]> = {};
      const live: Record<string, boolean> = {};
      for (const r of results) {
        candles[r.symbol] = r.candles;
        live[r.symbol] = r.live;
      }
      setCandlesBySymbol(candles);
      setLiveBySymbol(live);
      setLoadingPrices(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const rescore = () => {
      setNonce((n) => n + 1);
      setLastScanned(new Date());
    };
    rescore();
    const id = setInterval(rescore, RESCAN_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  const rows: Row[] = useMemo(() => {
    return SCAN_UNIVERSE.map((symbol) => {
      const candles = candlesBySymbol[symbol] ?? buildCandles(symbol);
      const setup = buildSetup(symbol, candles, nonce);
      return {
        symbol,
        price: candles[candles.length - 1].c,
        isLive: liveBySymbol[symbol] ?? false,
        setup,
        rr: riskReward(setup),
      };
    });
  }, [candlesBySymbol, liveBySymbol, nonce]);

  const filtered = rows
    .filter((r) => biasFilter === "all" || r.setup.bias === biasFilter)
    .sort((a, b) => {
      if (sortKey === "confidence") return b.setup.confidence - a.setup.confidence;
      if (sortKey === "rr") return b.rr - a.rr;
      return a.symbol.localeCompare(b.symbol);
    });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg tracking-wide">Scanner</h1>
          <p className="text-xs text-ink-400">
            Real prices, placeholder AI setup scoring — see TODOs in this page and lib/mock-setup.ts for the real
            screening/scoring endpoints to wire up.
          </p>
        </div>
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-ink-400">
          <span>
            re-scores every {RESCAN_INTERVAL_MS / 1000}s · prices fetched once on load
            {lastScanned && <> · last scan {fmt.time(lastScanned.toISOString())}</>}
          </span>
          <button
            onClick={() => {
              setNonce((n) => n + 1);
              setLastScanned(new Date());
            }}
            className="rounded border border-ink-800 px-2 py-1 text-ink-100 hover:border-amber-signal hover:text-amber-signal"
          >
            rescan now
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <div className="flex gap-1">
          {(["all", "long", "short"] as const).map((b) => (
            <button
              key={b}
              onClick={() => setBiasFilter(b)}
              className={`rounded border px-3 py-1.5 text-xs uppercase tracking-widest transition-colors ${
                biasFilter === b
                  ? "border-amber-signal text-amber-signal"
                  : "border-ink-800 text-ink-400 hover:border-ink-400 hover:text-ink-100"
              }`}
            >
              {b}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-400">
          sort by
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="figure rounded border border-ink-800 bg-ink-950 px-2 py-1 text-xs text-ink-100"
          >
            <option value="confidence">confidence</option>
            <option value="rr">risk/reward</option>
            <option value="symbol">symbol</option>
          </select>
        </div>
        {loadingPrices && <span className="figure animate-pulse text-xs text-ink-400">loading prices…</span>}
      </div>

      <Panel title={`${filtered.length} setups`} right={<PreviewBadge />}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-800 text-left text-[10px] uppercase tracking-widest text-ink-400">
                <th className="py-1.5 pr-4 font-normal">symbol</th>
                <th className="py-1.5 pr-4 font-normal">price</th>
                <th className="py-1.5 pr-4 font-normal">confidence</th>
                <th className="py-1.5 pr-4 font-normal">bias</th>
                <th className="py-1.5 pr-4 font-normal">buy zone</th>
                <th className="py-1.5 pr-4 font-normal">stop</th>
                <th className="py-1.5 pr-4 font-normal">target</th>
                <th className="py-1.5 pr-4 font-normal">r/r</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.symbol} className="border-b border-ink-800/50 last:border-0 hover:bg-ink-800/30">
                  <td className="figure py-1.5 pr-4">
                    <Link href={`/stock/${r.symbol}`} className="text-amber-signal hover:underline">
                      {r.symbol}
                    </Link>
                  </td>
                  <td className="figure py-1.5 pr-4">
                    <span title={r.isLive ? "live · alpaca" : "placeholder — fetch failed"}>
                      {fmt.num(r.price, 2)}
                      {!r.isLive && <span className="ml-1 text-ink-400">~</span>}
                    </span>
                  </td>
                  <td className="py-1.5 pr-4">
                    <div className="flex items-center gap-2">
                      <ConfidenceStamp level={r.setup.confidenceLevel} size="sm" />
                      <span className="figure text-xs text-ink-400">{fmt.pct(r.setup.confidence, 0)}</span>
                    </div>
                  </td>
                  <td className={`figure py-1.5 pr-4 ${r.setup.bias === "long" ? "text-gain" : "text-loss"}`}>
                    {r.setup.bias}
                  </td>
                  <td className="figure py-1.5 pr-4 text-ink-400">
                    {fmt.num(r.setup.buyZone[0], 2)}–{fmt.num(r.setup.buyZone[1], 2)}
                  </td>
                  <td className="figure py-1.5 pr-4 text-loss">{fmt.num(r.setup.stopLoss, 2)}</td>
                  <td className="figure py-1.5 pr-4 text-gain">{fmt.num(r.setup.profitTarget, 2)}</td>
                  <td className="figure py-1.5 pr-4">1:{r.rr.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[10px] text-ink-400">~ next to a price means the live fetch failed and it&apos;s a placeholder.</p>
      </Panel>
    </div>
  );
}
