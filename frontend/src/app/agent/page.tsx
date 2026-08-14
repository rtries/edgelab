"use client";
/** Agent: "what is the bot doing?" — the whole point per the product
 * spec is that a user should never wonder. One status call, one
 * activity feed, one start/stop control. Paper only — the enable
 * toggle here is the same ops_data/agent_config.json flag the
 * Telegram bot and the background auto-trader already read; this page
 * doesn't introduce a second source of truth for "is the agent on."
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { ErrorBox, Loading, Panel, PreviewBadge } from "@/components/ui";
import { api, fmt, type AgentActivityEvent, type AgentStatus } from "@/lib/api";

const ACTION_LABEL: Record<string, string> = {
  BUY_NOW: "Entry available",
  SELL_NOW: "Exit signal",
  WAIT: "Watching for entry",
  WATCH: "Watching",
  NO_TRADE: "Rejected — insufficient evidence",
};

const ACTION_TONE: Record<string, string> = {
  BUY_NOW: "text-gain",
  SELL_NOW: "text-loss",
  WAIT: "text-amber-signal",
  WATCH: "text-ink-400",
  NO_TRADE: "text-loss/70",
};

const KIND_TONE: Record<string, string> = {
  executed: "text-gain",
  rejected: "text-ink-400",
  signal_received: "text-amber-signal",
  scan_note: "text-ink-400",
};

export default function AgentPage() {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [activity, setActivity] = useState<AgentActivityEvent[] | null>(null);
  const [toggling, setToggling] = useState(false);

  function refresh() {
    api.agentStatus().then(setStatus).catch((e) => setStatusError(String(e)));
    api.agentActivity(30).then(setActivity).catch(() => setActivity([]));
  }
  useEffect(refresh, []);
  useEffect(() => {
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, []);

  async function toggle() {
    if (!status) return;
    setToggling(true);
    try {
      const r = status.enabled ? await api.disableAgent() : await api.enableAgent();
      setStatus({ ...status, enabled: r.enabled });
      refresh();
    } finally {
      setToggling(false);
    }
  }

  if (statusError) return <ErrorBox error={statusError} />;
  if (!status) return <Loading label="loading agent" />;

  const cash = Number(status.account.cash);
  const dayPl = Number(status.account.equity) - Number(status.account.last_equity);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg tracking-wide">Edge Agent</h1>
          <p className="text-xs text-ink-400">Paper mode — fake money, real order matching. Never live.</p>
        </div>
        <button
          onClick={toggle}
          disabled={toggling || status.emergency_stop_active}
          className={`rounded border px-4 py-2 text-xs uppercase tracking-widest transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
            status.enabled
              ? "border-loss text-loss hover:bg-loss/10"
              : "border-gain text-gain hover:bg-gain/10"
          }`}
        >
          {toggling ? "…" : status.enabled ? "Stop agent" : "Start agent"}
        </button>
      </div>

      {status.emergency_stop_active && (
        <div className="rounded border border-loss/60 bg-loss/10 p-3 text-sm text-loss">
          Emergency stop is active on this account — the agent will not trade until it&apos;s cleared in{" "}
          <Link href="/connections" className="underline">Connections</Link>.
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Panel className="text-center">
          <div className="flex items-center justify-center gap-1.5 text-[10px] uppercase tracking-widest text-ink-400">
            <span className={`h-1.5 w-1.5 rounded-full ${status.enabled ? "bg-gain" : "bg-ink-400"}`} />
            Status
          </div>
          <div className={`figure mt-1 text-lg ${status.enabled ? "text-gain" : "text-ink-100"}`}>
            {status.enabled ? "Active" : "Stopped"}
          </div>
        </Panel>
        <Panel className="text-center">
          <div className="text-[10px] uppercase tracking-widest text-ink-400">Per-trade size</div>
          <div className="figure mt-1 text-lg text-ink-100">{fmt.num(status.allocation_per_trade_usd, 0)}</div>
        </Panel>
        <Panel className="text-center">
          <div className="text-[10px] uppercase tracking-widest text-ink-400">Today&apos;s P/L</div>
          <div className={`figure mt-1 text-lg ${dayPl >= 0 ? "text-gain" : "text-loss"}`}>{fmt.signed(dayPl, 0)}</div>
        </Panel>
        <Panel className="text-center">
          <div className="text-[10px] uppercase tracking-widest text-ink-400">Positions</div>
          <div className="figure mt-1 text-lg text-ink-100">{status.positions.length}</div>
        </Panel>
      </div>

      <p className="text-[10px] text-ink-400">
        cash available {fmt.num(cash, 0)} · buying power {fmt.num(Number(status.account.buying_power), 0)}
      </p>

      <Panel title="What I'm doing" right={<PreviewBadge />}>
        {status.watchlist.length === 0 ? (
          <div className="py-4 text-center text-sm text-ink-400">Nothing on the watchlist right now.</div>
        ) : (
          <div className="divide-y divide-ink-800/60">
            {status.watchlist.map((w) => (
              <Link
                key={w.symbol}
                href={`/stock/${w.symbol}`}
                className="flex items-center justify-between gap-3 py-2 hover:bg-ink-800/30"
              >
                <span className="figure w-14 text-sm text-ink-100">{w.symbol}</span>
                <span className={`figure text-xs ${ACTION_TONE[w.action] ?? "text-ink-400"}`}>
                  {ACTION_LABEL[w.action] ?? w.action}
                </span>
                <span className="max-w-sm truncate text-right text-xs text-ink-400">{w.why}</span>
              </Link>
            ))}
          </div>
        )}
      </Panel>

      {status.positions.length > 0 && (
        <Panel title="Current positions">
          <div className="divide-y divide-ink-800/60">
            {status.positions.map((p) => {
              const pl = Number(p.unrealized_pl);
              return (
                <div key={p.symbol} className="flex items-center justify-between py-2">
                  <Link href={`/stock/${p.symbol}`} className="figure text-sm text-amber-signal hover:underline">
                    {p.symbol}
                  </Link>
                  <span className="figure text-xs text-ink-400">{p.qty} sh @ {fmt.num(Number(p.avg_entry_price), 2)}</span>
                  <span className={`figure text-xs ${pl >= 0 ? "text-gain" : "text-loss"}`}>
                    {fmt.signed(pl, 2)} ({fmt.pct(Number(p.unrealized_plpc), 1)})
                  </span>
                </div>
              );
            })}
          </div>
        </Panel>
      )}

      <Panel title="Activity">
        {activity === null ? (
          <Loading label="loading activity" />
        ) : activity.length === 0 ? (
          <div className="py-4 text-center text-sm text-ink-400">
            Nothing yet. Enable the agent, or send a signal from{" "}
            <Link href="/connections" className="text-amber-signal hover:underline">TradingView</Link>.
          </div>
        ) : (
          <div className="space-y-1.5">
            {activity.map((a, i) => (
              <div key={i} className="flex items-start gap-3 text-xs">
                <span className="figure w-16 shrink-0 text-ink-400">{fmt.time(a.ts).slice(11, 19)}</span>
                <span className={`shrink-0 uppercase tracking-widest ${KIND_TONE[a.kind] ?? "text-ink-400"}`}>
                  {a.kind.replace("_", " ")}
                </span>
                <span className="text-ink-100">{a.message}</span>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
