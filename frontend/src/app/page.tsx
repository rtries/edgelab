"use client";
/** Home: the beginner-facing landing page (product-pivot spec —
 * "what is EdgeLab doing for me?" answered in one screen, no quant
 * terminology required). Replaces the old quant Research Dashboard,
 * which moved to /research-dashboard (Research Lab).
 *
 * Reuses existing pieces rather than inventing new ones: the Decision
 * Engine endpoint (same one Session Mode and the Stock page use) for
 * "current opportunities", and the paper account/positions endpoints
 * for the account snapshot. No new backend.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { ErrorBox, Panel, PreviewBadge } from "@/components/ui";
import { api, fmt, mapWithConcurrency, type Decision, type PaperAccount, type PaperPosition } from "@/lib/api";
import { SCAN_UNIVERSE } from "@/lib/mock-setup";

const ACTION_LABEL: Record<Decision["action"], string> = {
  BUY_NOW: "Entry available",
  SELL_NOW: "Exit signal",
  WAIT: "Wait",
  WATCH: "Watching",
  NO_TRADE: "No trade",
};

const ACTION_TONE: Record<Decision["action"], string> = {
  BUY_NOW: "border-gain text-gain",
  SELL_NOW: "border-loss text-loss",
  WAIT: "border-amber-signal text-amber-signal",
  WATCH: "border-ink-400 text-ink-100",
  NO_TRADE: "border-loss/60 text-loss",
};

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning.";
  if (h < 18) return "Good afternoon.";
  return "Good evening.";
}

export default function Home() {
  const [account, setAccount] = useState<PaperAccount | null>(null);
  const [positions, setPositions] = useState<PaperPosition[] | null>(null);
  const [accountError, setAccountError] = useState<string | null>(null);

  const [opportunities, setOpportunities] = useState<Decision[]>([]);
  const [oppsLoading, setOppsLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.paperAccount(), api.paperPositions()])
      .then(([acc, pos]) => {
        setAccount(acc);
        setPositions(pos);
      })
      .catch((e) => setAccountError(String(e)));
  }, []);

  useEffect(() => {
    let cancelled = false;
    mapWithConcurrency(SCAN_UNIVERSE.slice(0, 8) as unknown as string[], 4, (s) =>
      api.decision(s).catch(() => null),
    ).then((results) => {
      if (cancelled) return;
      setOpportunities(results.filter((d): d is Decision => d !== null));
      setOppsLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const equity = account ? Number(account.equity) : null;
  const lastEquity = account ? Number(account.last_equity) : null;
  const dayPl = equity != null && lastEquity != null ? equity - lastEquity : null;

  const actionable = opportunities.filter((d) => d.action !== "NO_TRADE");
  const rest = opportunities.filter((d) => d.action === "NO_TRADE");
  const ordered = [...actionable, ...rest];

  return (
    <div className="space-y-4">
      <h1 className="text-xl tracking-wide text-ink-100">{greeting()}</h1>

      {accountError && <ErrorBox error={accountError} />}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Panel className="text-center">
          <div className="text-[10px] uppercase tracking-widest text-ink-400">Account</div>
          <div className="figure mt-1 text-lg text-ink-100">{equity != null ? fmt.num(equity, 0) : "—"}</div>
        </Panel>
        <Panel className="text-center">
          <div className="text-[10px] uppercase tracking-widest text-ink-400">Today</div>
          <div className={`figure mt-1 text-lg ${dayPl == null ? "text-ink-100" : dayPl >= 0 ? "text-gain" : "text-loss"}`}>
            {dayPl != null ? fmt.signed(dayPl, 0) : "—"}
          </div>
        </Panel>
        <Panel className="text-center">
          <div className="text-[10px] uppercase tracking-widest text-ink-400">Open positions</div>
          <div className="figure mt-1 text-lg text-ink-100">{positions ? positions.length : "—"}</div>
        </Panel>
        <Panel className="text-center">
          <div className="text-[10px] uppercase tracking-widest text-ink-400">Watching</div>
          <div className="figure mt-1 text-lg text-ink-100">
            {oppsLoading ? "—" : `${actionable.length} setup${actionable.length === 1 ? "" : "s"}`}
          </div>
        </Panel>
      </div>

      <Panel title="Current opportunities" right={<PreviewBadge />}>
        {oppsLoading ? (
          <div className="figure animate-pulse py-6 text-center text-sm text-ink-400">watching the market…</div>
        ) : ordered.length === 0 ? (
          <div className="py-6 text-center text-sm text-ink-400">Nothing to show yet.</div>
        ) : (
          <div className="divide-y divide-ink-800/60">
            {ordered.map((d) => (
              <Link
                key={d.symbol}
                href={`/stock/${d.symbol}`}
                className="flex items-center justify-between gap-3 py-2.5 hover:bg-ink-800/30"
              >
                <div className="flex items-center gap-3">
                  <span className="figure w-14 text-sm text-ink-100">{d.symbol}</span>
                  <span className={`figure inline-block rounded border px-2 py-0.5 text-[10px] uppercase tracking-widest ${ACTION_TONE[d.action]}`}>
                    {ACTION_LABEL[d.action]}
                  </span>
                </div>
                <span className="max-w-md truncate text-right text-xs text-ink-400">{d.why}</span>
              </Link>
            ))}
          </div>
        )}
      </Panel>

      <div className="flex gap-3 text-xs text-ink-400">
        <Link href="/session" className="rounded border border-ink-800 px-3 py-1.5 hover:border-amber-signal hover:text-amber-signal">
          Open Agent
        </Link>
        <Link href="/portfolio" className="rounded border border-ink-800 px-3 py-1.5 hover:border-amber-signal hover:text-amber-signal">
          View Account
        </Link>
      </div>
    </div>
  );
}
