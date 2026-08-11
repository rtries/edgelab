"use client";
/** Portfolio: real Alpaca PAPER account data — equity, cash, buying
 * power, day P/L, and open positions. Same shared-paper-account caveat
 * as the Trading page: this is whoever's paper account the configured
 * API keys point at, not per-EdgeLab-user. No live money, ever — see
 * app/api/v1/market.py's module docstring on the backend. */
import { useEffect, useState } from "react";
import Link from "next/link";
import { ErrorBox, Loading, Panel, Stat } from "@/components/ui";
import { api, fmt, type PaperAccount, type PaperPosition } from "@/lib/api";

export default function PortfolioPage() {
  const [account, setAccount] = useState<PaperAccount | null>(null);
  const [positions, setPositions] = useState<PaperPosition[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    setError(null);
    Promise.all([api.paperAccount(), api.paperPositions()])
      .then(([acc, pos]) => {
        setAccount(acc);
        setPositions(pos);
      })
      .catch((e) => setError(String(e)));
  }
  useEffect(refresh, []);

  const equity = account ? Number(account.equity) : null;
  const lastEquity = account ? Number(account.last_equity) : null;
  const dayPl = equity != null && lastEquity != null ? equity - lastEquity : null;
  const dayPlPct = dayPl != null && lastEquity ? dayPl / lastEquity : null;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg tracking-wide">Portfolio</h1>
          <p className="text-xs text-ink-400">
            Real Alpaca <span className="text-amber-signal">paper</span> account — fake money, real order
            matching. No live money exists on this page.
          </p>
        </div>
        <button
          onClick={refresh}
          className="text-[10px] uppercase tracking-widest text-ink-400 hover:text-amber-signal"
        >
          refresh
        </button>
      </div>

      {error && <ErrorBox error={error} />}

      {!error && !account && <Loading label="loading account" />}

      {account && (
        <Panel title="Account">
          <div className="flex flex-wrap gap-8">
            <Stat label="equity" value={fmt.num(equity, 2)} />
            <Stat label="cash" value={fmt.num(Number(account.cash), 2)} />
            <Stat label="buying power" value={fmt.num(Number(account.buying_power), 2)} />
            <Stat
              label="day P/L"
              value={dayPl != null ? `${fmt.signed(dayPl, 2)} (${fmt.pct(dayPlPct, 1)})` : "—"}
              tone={dayPl == null ? "neutral" : dayPl >= 0 ? "gain" : "loss"}
            />
            <Stat label="status" value={account.status} />
          </div>
        </Panel>
      )}

      <Panel title={positions ? `${positions.length} open position${positions.length === 1 ? "" : "s"}` : "Positions"}>
        {!error && !positions ? (
          <Loading label="loading positions" />
        ) : positions && positions.length === 0 ? (
          <div className="py-6 text-center text-sm text-ink-400">
            No open positions. Place a paper trade from{" "}
            <Link href="/trading" className="text-amber-signal hover:underline">Trading</Link>.
          </div>
        ) : positions ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-800 text-left text-[10px] uppercase tracking-widest text-ink-400">
                  <th className="py-1.5 pr-4 font-normal">symbol</th>
                  <th className="py-1.5 pr-4 font-normal">side</th>
                  <th className="py-1.5 pr-4 font-normal">qty</th>
                  <th className="py-1.5 pr-4 font-normal">avg entry</th>
                  <th className="py-1.5 pr-4 font-normal">current</th>
                  <th className="py-1.5 pr-4 font-normal">market value</th>
                  <th className="py-1.5 pr-4 font-normal">unrealized P/L</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => {
                  const pl = Number(p.unrealized_pl);
                  return (
                    <tr key={p.symbol} className="border-b border-ink-800/50 last:border-0 hover:bg-ink-800/30">
                      <td className="figure py-1.5 pr-4">
                        <Link href={`/stock/${p.symbol}`} className="text-amber-signal hover:underline">
                          {p.symbol}
                        </Link>
                      </td>
                      <td className="figure py-1.5 pr-4 text-ink-400">{p.side}</td>
                      <td className="figure py-1.5 pr-4">{p.qty}</td>
                      <td className="figure py-1.5 pr-4">{fmt.num(Number(p.avg_entry_price), 2)}</td>
                      <td className="figure py-1.5 pr-4">{fmt.num(Number(p.current_price), 2)}</td>
                      <td className="figure py-1.5 pr-4">{fmt.num(Number(p.market_value), 2)}</td>
                      <td className={`figure py-1.5 pr-4 ${pl >= 0 ? "text-gain" : "text-loss"}`}>
                        {fmt.signed(pl, 2)} ({fmt.pct(Number(p.unrealized_plpc), 1)})
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
