"use client";
/** Trading: simple buy/sell for any symbol, always through Alpaca's
 * PAPER environment — see the backend module docstring in
 * app/api/v1/market.py for why this is deliberately separate from the
 * deployment-gated Alpaca broker and never touches live money.
 */
import { useEffect, useState } from "react";
import { SymbolSearch } from "@/components/symbol-search";
import { ErrorBox, Panel } from "@/components/ui";
import { api, fmt, type PaperOrder } from "@/lib/api";

export default function TradingPage() {
  const [symbol, setSymbol] = useState("AAPL");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [orderType, setOrderType] = useState<"market" | "limit">("market");
  const [qty, setQty] = useState("1");
  const [limitPrice, setLimitPrice] = useState("");
  const [lastPrice, setLastPrice] = useState<number | null>(null);
  const [priceError, setPriceError] = useState<string | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<PaperOrder | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [orders, setOrders] = useState<PaperOrder[] | null>(null);
  const [ordersError, setOrdersError] = useState<string | null>(null);

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
      .paperOrders(15)
      .then(setOrders)
      .catch((e) => setOrdersError(String(e)));
  }
  useEffect(refreshOrders, []);

  const qtyNum = Number(qty) || 0;
  const refPrice = orderType === "limit" ? Number(limitPrice) || lastPrice : lastPrice;
  const estimatedCost = refPrice != null ? refPrice * qtyNum : null;

  async function submit() {
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const order = await api.submitPaperOrder({
        symbol,
        side,
        qty: qtyNum,
        order_type: orderType,
        limit_price: orderType === "limit" ? Number(limitPrice) : undefined,
      });
      setResult(order);
      refreshOrders();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit = qtyNum > 0 && (orderType === "market" || Number(limitPrice) > 0) && !submitting;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg tracking-wide">Trading</h1>
        <p className="text-xs text-ink-400">
          Paper trading only — orders go to Alpaca&apos;s paper environment (fake money, real order matching). No
          live-money path exists on this page.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <Panel title="Place order">
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-[10px] uppercase tracking-widest text-ink-400">symbol</label>
              <SymbolSearch onSelect={setSymbol} placeholder={symbol} />
              <div className="mt-1 text-xs text-ink-400">
                selected: <span className="figure text-ink-100">{symbol}</span>
                {lastPrice != null && <> · last <span className="figure text-ink-100">{fmt.num(lastPrice, 2)}</span></>}
                {priceError && <span className="text-loss"> · couldn&apos;t fetch price</span>}
              </div>
            </div>

            <div className="flex gap-1">
              {(["buy", "sell"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setSide(s)}
                  className={`flex-1 rounded border py-1.5 text-xs uppercase tracking-widest transition-colors ${
                    side === s
                      ? s === "buy"
                        ? "border-gain text-gain"
                        : "border-loss text-loss"
                      : "border-ink-800 text-ink-400 hover:border-ink-400 hover:text-ink-100"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>

            <div className="flex gap-1">
              {(["market", "limit"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setOrderType(t)}
                  className={`flex-1 rounded border py-1.5 text-xs uppercase tracking-widest transition-colors ${
                    orderType === t
                      ? "border-amber-signal text-amber-signal"
                      : "border-ink-800 text-ink-400 hover:border-ink-400 hover:text-ink-100"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>

            <div>
              <label className="mb-1 block text-[10px] uppercase tracking-widest text-ink-400">quantity (shares)</label>
              <input
                type="number"
                min="0"
                step="1"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                className="figure w-full rounded border border-ink-800 bg-ink-950 px-3 py-1.5 text-sm text-ink-100 focus:border-amber-signal focus:outline-none"
              />
            </div>

            {orderType === "limit" && (
              <div>
                <label className="mb-1 block text-[10px] uppercase tracking-widest text-ink-400">limit price</label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={limitPrice}
                  onChange={(e) => setLimitPrice(e.target.value)}
                  placeholder={lastPrice != null ? fmt.num(lastPrice, 2) : "0.00"}
                  className="figure w-full rounded border border-ink-800 bg-ink-950 px-3 py-1.5 text-sm text-ink-100 focus:border-amber-signal focus:outline-none"
                />
              </div>
            )}

            <div className="rounded border border-ink-800 bg-ink-950 px-3 py-2 text-xs">
              <div className="flex justify-between text-ink-400">
                <span>estimated cost</span>
                <span className="figure text-ink-100">
                  {estimatedCost != null ? fmt.num(estimatedCost, 2) : "—"}
                </span>
              </div>
              {orderType === "market" && (
                <div className="mt-1 text-[10px] text-ink-400">
                  market orders fill at whatever the price is when submitted — this estimate uses the last close.
                </div>
              )}
            </div>

            <button
              disabled={!canSubmit}
              onClick={submit}
              className={`w-full rounded border py-2 text-xs uppercase tracking-widest transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                side === "buy" ? "border-gain text-gain hover:bg-gain/10" : "border-loss text-loss hover:bg-loss/10"
              }`}
            >
              {submitting ? "submitting…" : `${side} ${qtyNum || 0} ${symbol} · paper`}
            </button>

            {error && <ErrorBox error={error} />}
            {result && (
              <div className="rounded border border-gain/50 bg-gain/10 p-3 text-xs">
                <div className="mb-1 font-medium text-gain">order submitted</div>
                <div className="figure text-ink-400">
                  {result.side} {result.qty} {result.symbol} · {result.type} · status: {result.status}
                </div>
              </div>
            )}
          </div>
        </Panel>

        <Panel title="Recent paper orders" right={
          <button onClick={refreshOrders} className="text-[10px] uppercase tracking-widest text-ink-400 hover:text-amber-signal">
            refresh
          </button>
        }>
          {ordersError ? (
            <ErrorBox error={ordersError} />
          ) : orders === null ? (
            <div className="figure animate-pulse text-sm text-ink-400">loading…</div>
          ) : orders.length === 0 ? (
            <div className="py-6 text-center text-sm text-ink-400">no orders yet</div>
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
                  {orders.map((o) => (
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
