"use client";
/** Scanner: runs the AI setup scoring across a symbol universe and ranks
 * by confidence — "find me the best setups right now."
 *
 * TODO(backend): SCAN_UNIVERSE is a hardcoded placeholder list. Replace
 * with the user's real watchlist (once one exists) or a broader
 * screenable universe from a market-data provider. The per-symbol
 * scoring itself is the same placeholder used by the Markets page —
 * see @/lib/mock-setup for the TODO(backend) notes on that.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ConfidenceStamp, Panel } from "@/components/ui";
import { fmt } from "@/lib/api";
import { SCAN_UNIVERSE, buildCandles, buildSetup, riskReward, type Setup } from "@/lib/mock-setup";

const RESCAN_INTERVAL_MS = 30_000;

type Row = {
  symbol: string;
  price: number;
  setup: Setup;
  rr: number;
};

const CONFIDENCE_ORDER: Record<Setup["confidenceLevel"], number> = {
  strong: 3,
  moderate: 2,
  weak: 1,
  insufficient: 0,
};

type SortKey = "confidence" | "rr" | "symbol";

export default function ScannerPage() {
  const [biasFilter, setBiasFilter] = useState<"all" | "long" | "short">("all");
  const [sortKey, setSortKey] = useState<SortKey>("confidence");
  const [nonce, setNonce] = useState(0);
  const [lastScanned, setLastScanned] = useState<Date | null>(null);

  useEffect(() => {
    const rescan = () => {
      setNonce((n) => n + 1);
      setLastScanned(new Date());
    };
    rescan();
    const id = setInterval(rescan, RESCAN_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  const rows: Row[] = useMemo(() => {
    return SCAN_UNIVERSE.map((symbol) => {
      const candles = buildCandles(symbol);
      const setup = buildSetup(symbol, candles, nonce);
      return { symbol, price: candles[candles.length - 1].c, setup, rr: riskReward(setup) };
    });
  }, [nonce]);

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
            Ranks a placeholder symbol universe by AI setup confidence — see TODOs in this page and lib/mock-setup.ts
            for the real screening/scoring endpoints to wire up.
          </p>
        </div>
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-ink-400">
          <span>
            rescans every {RESCAN_INTERVAL_MS / 1000}s
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
      </div>

      <Panel title={`${filtered.length} setups`}>
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
                    <Link href={`/markets?symbol=${r.symbol}`} className="text-amber-signal hover:underline">
                      {r.symbol}
                    </Link>
                  </td>
                  <td className="figure py-1.5 pr-4">{fmt.num(r.price, 2)}</td>
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
      </Panel>
    </div>
  );
}
