"use client";
/** Shared paper order ticket — market/limit/stop/stop-limit/bracket,
 * review-before-submit. Used by both the Trading and Session pages so
 * the order logic (and its safety review step) lives in exactly one
 * place. Always paper — see app/api/v1/market.py's module docstring. */
import { type ReactNode, useEffect, useState } from "react";
import { ErrorBox, Panel } from "@/components/ui";
import { api, fmt, type PaperOrder, type PaperOrderType } from "@/lib/api";

const ORDER_TYPES: { value: PaperOrderType; label: string }[] = [
  { value: "market", label: "Market" },
  { value: "limit", label: "Limit" },
  { value: "stop", label: "Stop" },
  { value: "stop_limit", label: "Stop-Limit" },
  { value: "bracket", label: "Bracket" },
];

export function OrderTicket({
  symbol,
  lastPrice,
  onFilled,
  header,
}: {
  symbol: string;
  lastPrice: number | null;
  onFilled: () => void;
  header?: ReactNode;
}) {
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [orderType, setOrderType] = useState<PaperOrderType>("market");
  const [qty, setQty] = useState("1");
  const [limitPrice, setLimitPrice] = useState("");
  const [stopPrice, setStopPrice] = useState("");
  const [bracketEntryType, setBracketEntryType] = useState<"market" | "limit">("market");
  const [takeProfitPrice, setTakeProfitPrice] = useState("");
  const [stopLossPrice, setStopLossPrice] = useState("");

  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<PaperOrder | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Any change after review starts invalidates it — never submit an
  // order the tester didn't actually confirm as-shown.
  useEffect(() => {
    setConfirming(false);
    setResult(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, side, qty, orderType, limitPrice, stopPrice, bracketEntryType, takeProfitPrice, stopLossPrice]);

  const qtyNum = Number(qty) || 0;
  const refPrice =
    orderType === "limit" || (orderType === "bracket" && bracketEntryType === "limit")
      ? Number(limitPrice) || lastPrice
      : lastPrice;
  const estimatedCost = refPrice != null ? refPrice * qtyNum : null;

  const canSubmit =
    qtyNum > 0 &&
    !submitting &&
    (orderType !== "limit" || Number(limitPrice) > 0) &&
    (orderType !== "stop" || Number(stopPrice) > 0) &&
    (orderType !== "stop_limit" || (Number(stopPrice) > 0 && Number(limitPrice) > 0)) &&
    (orderType !== "bracket" ||
      (Number(takeProfitPrice) > 0 &&
        Number(stopLossPrice) > 0 &&
        (bracketEntryType !== "limit" || Number(limitPrice) > 0)));

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const order = await api.submitPaperOrder({
        symbol,
        side,
        qty: qtyNum,
        order_type: orderType,
        limit_price: limitPrice ? Number(limitPrice) : undefined,
        stop_price: stopPrice ? Number(stopPrice) : undefined,
        bracket_entry_type: orderType === "bracket" ? bracketEntryType : undefined,
        take_profit_price: orderType === "bracket" ? Number(takeProfitPrice) : undefined,
        stop_loss_price: orderType === "bracket" ? Number(stopLossPrice) : undefined,
      });
      setResult(order);
      setConfirming(false);
      onFilled();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  function orderSummary(): string {
    if (orderType === "bracket") {
      return `${side} ${qtyNum} ${symbol} · bracket ${bracketEntryType}${bracketEntryType === "limit" ? ` @ ${fmt.num(Number(limitPrice), 2)}` : ""} · TP ${fmt.num(Number(takeProfitPrice), 2)} / SL ${fmt.num(Number(stopLossPrice), 2)}`;
    }
    if (orderType === "stop_limit") {
      return `${side} ${qtyNum} ${symbol} · stop-limit · stop ${fmt.num(Number(stopPrice), 2)} / limit ${fmt.num(Number(limitPrice), 2)}`;
    }
    if (orderType === "stop") {
      return `${side} ${qtyNum} ${symbol} · stop ${fmt.num(Number(stopPrice), 2)}`;
    }
    if (orderType === "limit") {
      return `${side} ${qtyNum} ${symbol} · limit ${fmt.num(Number(limitPrice), 2)}`;
    }
    return `${side} ${qtyNum} ${symbol} · market`;
  }

  return (
    <Panel title={`Order · ${symbol}`}>
      <div className="space-y-3">
        {header}

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

        <div className="flex flex-wrap gap-1">
          {ORDER_TYPES.map((t) => (
            <button
              key={t.value}
              onClick={() => setOrderType(t.value)}
              className={`flex-1 rounded border px-1 py-1.5 text-[11px] uppercase tracking-widest transition-colors ${
                orderType === t.value
                  ? "border-amber-signal text-amber-signal"
                  : "border-ink-800 text-ink-400 hover:border-ink-400 hover:text-ink-100"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <input
          type="number"
          min="0"
          step="1"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          placeholder="quantity"
          className="figure w-full rounded border border-ink-800 bg-ink-950 px-3 py-1.5 text-sm text-ink-100 focus:border-amber-signal focus:outline-none"
        />

        {(orderType === "limit" || orderType === "stop_limit") && (
          <PriceInput label="limit price" value={limitPrice} onChange={setLimitPrice} placeholder={lastPrice} />
        )}
        {(orderType === "stop" || orderType === "stop_limit") && (
          <PriceInput label="stop price" value={stopPrice} onChange={setStopPrice} placeholder={lastPrice} />
        )}

        {orderType === "bracket" && (
          <div className="space-y-2 rounded border border-ink-800 p-2">
            <div className="flex gap-1">
              {(["market", "limit"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setBracketEntryType(t)}
                  className={`flex-1 rounded border py-1 text-[10px] uppercase tracking-widest transition-colors ${
                    bracketEntryType === t
                      ? "border-amber-signal text-amber-signal"
                      : "border-ink-800 text-ink-400 hover:border-ink-400 hover:text-ink-100"
                  }`}
                >
                  entry: {t}
                </button>
              ))}
            </div>
            {bracketEntryType === "limit" && (
              <PriceInput label="entry limit price" value={limitPrice} onChange={setLimitPrice} placeholder={lastPrice} />
            )}
            <PriceInput label="take profit price" value={takeProfitPrice} onChange={setTakeProfitPrice} tone="gain" />
            <PriceInput label="stop loss price" value={stopLossPrice} onChange={setStopLossPrice} tone="loss" />
          </div>
        )}

        <div className="flex justify-between rounded border border-ink-800 bg-ink-950 px-3 py-2 text-xs text-ink-400">
          <span>estimated value</span>
          <span className="figure text-ink-100">{estimatedCost != null ? fmt.num(estimatedCost, 2) : "—"}</span>
        </div>

        {!confirming ? (
          <button
            disabled={!canSubmit}
            onClick={() => setConfirming(true)}
            className={`w-full rounded border py-2 text-xs uppercase tracking-widest transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
              side === "buy" ? "border-gain text-gain hover:bg-gain/10" : "border-loss text-loss hover:bg-loss/10"
            }`}
          >
            review {side} {qtyNum || 0} {symbol}
          </button>
        ) : (
          <div className="space-y-2 rounded border border-amber-signal/60 bg-amber-signal/5 p-3">
            <div className="text-[10px] uppercase tracking-widest text-amber-signal">this is paper trading</div>
            <div className="figure text-sm text-ink-100">{orderSummary()}</div>
            <div className="flex gap-2 pt-1">
              <button
                onClick={() => setConfirming(false)}
                className="flex-1 rounded border border-ink-800 py-1.5 text-xs uppercase tracking-widest text-ink-100 hover:border-ink-400"
              >
                back
              </button>
              <button
                disabled={submitting}
                onClick={submit}
                className={`flex-1 rounded border py-1.5 text-xs uppercase tracking-widest disabled:cursor-not-allowed disabled:opacity-40 ${
                  side === "buy"
                    ? "border-gain bg-gain/10 text-gain hover:bg-gain/20"
                    : "border-loss bg-loss/10 text-loss hover:bg-loss/20"
                }`}
              >
                {submitting ? "submitting…" : "confirm paper order"}
              </button>
            </div>
          </div>
        )}

        {error && <ErrorBox error={error} />}
        {result && (
          <div className="rounded border border-gain/50 bg-gain/10 p-2 text-xs text-gain">
            order submitted · status: {result.status}
          </div>
        )}
      </div>
    </Panel>
  );
}

function PriceInput({
  label,
  value,
  onChange,
  placeholder,
  tone,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: number | null;
  tone?: "gain" | "loss";
}) {
  return (
    <div>
      <label className="mb-1 block text-[10px] uppercase tracking-widest text-ink-400">{label}</label>
      <input
        type="number"
        min="0"
        step="0.01"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder != null ? fmt.num(placeholder, 2) : "0.00"}
        className={`figure w-full rounded border bg-ink-950 px-3 py-1.5 text-sm focus:outline-none ${
          tone === "gain"
            ? "border-gain/40 text-gain focus:border-gain"
            : tone === "loss"
              ? "border-loss/40 text-loss focus:border-loss"
              : "border-ink-800 text-ink-100 focus:border-amber-signal"
        }`}
      />
    </div>
  );
}
