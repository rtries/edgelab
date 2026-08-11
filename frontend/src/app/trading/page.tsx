"use client";
/** Trading: simple buy/sell for any symbol, always through Alpaca's
 * PAPER environment — see the backend module docstring in
 * app/api/v1/market.py for why this is deliberately separate from the
 * deployment-gated Alpaca broker and never touches live money.
 *
 * Order form itself lives in @/components/order-ticket, shared with
 * the Session page so the (safety-critical) review-before-submit logic
 * exists in exactly one place.
 */
import { useEffect, useState } from "react";
import { SymbolSearch } from "@/components/symbol-search";
import { OrderTicket } from "@/components/order-ticket";
import { ErrorBox, Panel } from "@/components/ui";
import { api, fmt, type PaperOrder } from "@/lib/api";

export default function TradingPage() {
  const [symbol, setSymbol] = useState("AAPL");
  const [lastPrice, setLastPrice] = useState<number | null>(null);
  const [priceError, setPriceError] = useState<string | null>(null);

  const [orders, setOrders] = useState<PaperOrder[] | null>(null);
  const [ordersError, setOrdersError] = useState<string | null>(null);
  const [orderFilter, setOrderFilter] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLastPrice(null);
    setPriceError(null);
    api
      .marketBars(symbol, "1Day", 2)
      .then((bars) => {
        if (cancelled) return;
        setLastPrice(bars[bars.length - 1].c);
      })
      .catch((e) => {
        if (cancelled) return;
        setPriceError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  function refreshOrders() {
    api
      .paperOrders(100)
      .then(setOrders)
      .catch((e) => setOrdersError(String(e)));
  }
  useEffect(refreshOrders, []);

  const filteredOrders = orders?.filter(
    (o) => orderFilter.trim() === "" || o.symbol.toUpperCase().includes(orderFilter.trim().toUpperCase()),
  );

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg tracking-wide">Trading</h1>
        <p className="text-xs text-ink-400">
          Paper trading only — orders go to Alpaca&apos;s paper environment (fake money, real order matching). No
          live-money path exists on this page. Market, limit, stop, stop-limit, and bracket orders supported.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <OrderTicket
          symbol={symbol}
          lastPrice={lastPrice}
          onFilled={refreshOrders}
          header={
            <div>
              <label className="mb-1 block text-[10px] uppercase tracking-widest text-ink-400">symbol</label>
              <SymbolSearch onSelect={setSymbol} placeholder={symbol} />
              <div className="mt-1 text-xs text-ink-400">
                selected: <span className="figure text-ink-100">{symbol}</span>
                {lastPrice != null && <> · last <span className="figure text-ink-100">{fmt.num(lastPrice, 2)}</span></>}
                {priceError && <span className="text-loss"> · couldn&apos;t fetch price</span>}
              </div>
            </div>
          }
        />

        <Panel title="Recent paper orders" right={
          <button onClick={refreshOrders} className="text-[10px] uppercase tracking-widest text-ink-400 hover:text-amber-signal">
            refresh
          </button>
        }>
          <div className="mb-3 space-y-1">
            <input
              value={orderFilter}
              onChange={(e) => setOrderFilter(e.target.value)}
              placeholder="filter by symbol…"
              className="figure w-48 rounded border border-ink-800 bg-ink-950 px-2 py-1 text-xs text-ink-100 focus:border-amber-signal focus:outline-none"
            />
            <p className="text-[10px] text-ink-400">
              This is the shared Alpaca paper account — it also shows orders placed by deployments run through the
              Alpaca broker integration, not just orders submitted from this page.
            </p>
          </div>
          {ordersError ? (
            <ErrorBox error={ordersError} />
          ) : orders === null ? (
            <div className="figure animate-pulse text-sm text-ink-400">loading…</div>
          ) : orders.length === 0 ? (
            <div className="py-6 text-center text-sm text-ink-400">no orders yet</div>
          ) : filteredOrders && filteredOrders.length === 0 ? (
            <div className="py-6 text-center text-sm text-ink-400">no orders match &quot;{orderFilter}&quot;</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-ink-800 text-left text-[10px] uppercase tracking-widest text-ink-400">
                    <th className="py-1.5 pr-4 font-normal">submitted</th>
                    <th className="py-1.5 pr-4 font-normal">symbol</th>
                    <th className="py-1.5 pr-4 font-normal">side</th>
                    <th className="py-1.5 pr-4 font-normal">qty</th>
                    <th className="py-1.5 pr-4 font-normal">type</th>
                    <th className="py-1.5 pr-4 font-normal">status</th>
                    <th className="py-1.5 pr-4 font-normal">fill price</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredOrders?.map((o) => (
                    <tr key={o.id} className="border-b border-ink-800/50 last:border-0">
                      <td className="figure py-1.5 pr-4 text-ink-400">{fmt.time(o.submitted_at)}</td>
                      <td className="figure py-1.5 pr-4">{o.symbol}</td>
                      <td className={`figure py-1.5 pr-4 ${o.side === "buy" ? "text-gain" : "text-loss"}`}>{o.side}</td>
                      <td className="figure py-1.5 pr-4">{o.qty}</td>
                      <td className="figure py-1.5 pr-4 text-ink-400">{o.type}</td>
                      <td className="figure py-1.5 pr-4">{o.status}</td>
                      <td className="figure py-1.5 pr-4">{o.filled_avg_price ? fmt.num(Number(o.filled_avg_price), 2) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
