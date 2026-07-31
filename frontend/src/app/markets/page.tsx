"use client";
/** Markets: the "search any stock" landing page. Picking a symbol opens
 * its research page at /stock/[symbol], which has the real chart, AI
 * setup, and Research tab. */
import { useRouter } from "next/navigation";
import { SymbolSearch } from "@/components/symbol-search";
import { SCAN_UNIVERSE } from "@/lib/mock-setup";

export default function MarketsPage() {
  const router = useRouter();
  const go = (s: string) => router.push(`/stock/${s}`);

  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center space-y-6 text-center">
      <div>
        <h1 className="text-2xl tracking-wide">Search any stock</h1>
        <p className="mt-1 text-sm text-ink-400">
          Chart, AI trade setup, and research — all in one place.
        </p>
      </div>
      <div className="w-full max-w-md">
        <SymbolSearch onSelect={go} placeholder="AAPL, TSLA, NVDA…" autoFocus />
      </div>
      <div>
        <div className="mb-2 text-[10px] uppercase tracking-widest text-ink-400">popular</div>
        <div className="flex flex-wrap justify-center gap-1">
          {SCAN_UNIVERSE.map((s) => (
            <button
              key={s}
              onClick={() => go(s)}
              className="figure rounded border border-ink-800 px-3 py-1.5 text-xs uppercase tracking-widest text-ink-400 transition-colors hover:border-amber-signal hover:text-amber-signal"
            >
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
