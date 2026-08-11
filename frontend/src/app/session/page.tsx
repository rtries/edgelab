"use client";
/** Session Mode: the one-screen trading workspace (spec section 10-19).
 * Watchlist -> chart+decision -> order ticket+positions, without
 * bouncing between Scanner/Markets/Stock/Trading/Portfolio.
 *
 * Deliberately reuses existing pieces rather than inventing new ones:
 * the same chart components, Decision Engine endpoint, order-confirm
 * flow, and positions data that already power the Stock/Trading/
 * Portfolio pages. No new backend beyond what those already call.
 *
 * Step 4: polling, not streaming. The backend is one small instance —
 * a websocket/SSE layer is real future work, not something to bolt on
 * casually. Polling every 30s for the selected symbol's chart/decision
 * and positions, every 90s for the watchlist (concurrency-capped, see
 * lib/api.mapWithConcurrency), and only while the tab is actually
 * visible — a background tab shouldn't keep polling a tiny backend for
 * data nobody's looking at.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { Candle } from "@/components/charts";
import { CandlestickChart, VolumeChart } from "@/components/charts";
import { ConfidenceStamp, ErrorBox, Panel, PreviewBadge, Stat } from "@/components/ui";
import { Term } from "@/components/glossary";
import { SymbolSearch } from "@/components/symbol-search";
import { api, fmt, mapWithConcurrency, type Decision, type PaperOrder, type PaperPosition } from "@/lib/api";
import { SCAN_UNIVERSE, buildCandles, buildSetup } from "@/lib/mock-setup";

const TIMEFRAMES: { label: string; timeframe: string; limit: number }[] = [
  { label: "1M", timeframe: "1Day", limit: 22 },
  { label: "3M", timeframe: "1Day", limit: 65 },
  { label: "6M", timeframe: "1Day", limit: 130 },
  { label: "1Y", timeframe: "1Day", limit: 260 },
];

const ACTION_LABEL: Record<Decision["action"], string> = {
  BUY_NOW: "Buy Now",
  SELL_NOW: "Sell Now",
  WAIT: "Wait",
  WATCH: "Watch",
  NO_TRADE: "No Trade",
};

const ACTION_TONE: Record<Decision["action"], string> = {
  BUY_NOW: "border-gain text-gain bg-gain/10",
  SELL_NOW: "border-loss text-loss bg-loss/10",
  WAIT: "border-amber-signal text-amber-signal bg-amber-signal/10",
  WATCH: "border-ink-400 text-ink-100 bg-ink-800/50",
  NO_TRADE: "border-loss/70 text-loss bg-loss/5",
};

type WatchRow = { symbol: string; price: number; changePct: number; isLive: boolean };

const POLL_MS = 30_000;

/** Ticks up every POLL_MS while the tab is visible; frozen (and caught
 * up on the next tick) while it's hidden. Effects that want to poll
 * just add `tick` to their dependency array. */
function usePollTick(intervalMs: number) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === "visible") setTick((t) => t + 1);
    }, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return tick;
}

export default function SessionPage() {
  const [symbol, setSymbol] = useState("AAPL");
  const [range, setRange] = useState(TIMEFRAMES[2]); // 6M default — session view favors recent action
  const [candles, setCandles] = useState<Candle[]>(() => buildCandles(symbol));
  const [isLive, setIsLive] = useState(false);
  const [chartLoading, setChartLoading] = useState(true);

  const [decision, setDecision] = useState<Decision | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  const [watchlist, setWatchlist] = useState<WatchRow[]>([]);
  const [watchLoading, setWatchLoading] = useState(true);

  const [positions, setPositions] = useState<PaperPosition[] | null>(null);
  const [positionsError, setPositionsError] = useState<string | null>(null);

  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const tick = usePollTick(POLL_MS);

  // --- chart (polls every tick for the selected symbol) ---
  useEffect(() => {
    let cancelled = false;
    setChartLoading(true);
    api
      .marketBars(symbol, range.timeframe, range.limit)
      .then((bars) => {
        if (cancelled) return;
        setCandles(bars.map((b) => ({ t: b.t, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v })));
        setIsLive(true);
        setLastUpdated(new Date());
      })
      .catch(() => {
        if (cancelled) return;
        setCandles(buildCandles(symbol, range.limit));
        setIsLive(false);
      })
      .finally(() => {
        if (!cancelled) setChartLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, range, tick]);

  // Clear stale decision immediately on symbol switch (not on poll ticks —
  // that would flicker) so a new symbol never briefly shows the old one's data.
  useEffect(() => {
    setDecision(null);
    setDecisionError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  // --- decision (polls every tick) ---
  useEffect(() => {
    let cancelled = false;
    api
      .decision(symbol)
      .then((d) => {
        if (cancelled) return;
        setDecision(d);
        setDecisionError(null);
      })
      .catch((e) => {
        if (!cancelled) setDecisionError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, tick]);

  // --- watchlist (real prices, cheap placeholder change%). Capped at 4
  // concurrent requests: the backend is a single tiny instance, and this
  // page already fires chart+decision+positions calls alongside it — an
  // uncapped 15-wide burst on top of those was enough to trip transient
  // connection failures on load. Polls every 3rd tick (~90s) — the
  // watchlist matters less moment-to-moment than the selected symbol.
  useEffect(() => {
    let cancelled = false;
    mapWithConcurrency(SCAN_UNIVERSE as unknown as string[], 4, (s) =>
      api
        .marketBars(s, "1Day", 2)
        .then((bars) => {
          const last = bars[bars.length - 1];
          const prev = bars[bars.length - 2] ?? last;
          return { symbol: s, price: last.c, changePct: prev.c ? (last.c - prev.c) / prev.c : 0, isLive: true };
        })
        .catch(() => {
          const c = buildCandles(s, 2);
          return { symbol: s, price: c[1].c, changePct: 0, isLive: false };
        }),
    ).then((rows) => {
      if (!cancelled) {
        setWatchlist(rows);
        setWatchLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Math.floor(tick / 3)]);

  // --- positions (polls every tick — one cheap call, worth keeping fresh) ---
  function refreshPositions() {
    setPositionsError(null);
    api.paperPositions().then(setPositions).catch((e) => setPositionsError(String(e)));
  }
  useEffect(refreshPositions, [tick]);

  const fallbackSetup = useMemo(() => buildSetup(symbol, candles), [symbol, candles]);
  const setup = decision
    ? {
        confidence: decision.confidence,
        confidenceLevel: decision.confidence_level,
        bias: decision.bias,
        buyZone: decision.entry_zone,
        stopLoss: decision.stop,
        profitTarget: decision.targets[0],
      }
    : fallbackSetup;

  const last = candles[candles.length - 1];
  const prev = candles[candles.length - 2] ?? last;
  const change = last.c - prev.c;
  const changePct = prev.c === 0 ? 0 : change / prev.c;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg tracking-wide">Session</h1>
          <p className="text-xs text-ink-400">
            One screen for the trading session: watchlist, chart, decision, and paper orders. Paper trading only.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] uppercase tracking-widest text-ink-400">
            {lastUpdated ? (
              <>auto-refreshing 30s · updated {fmt.time(lastUpdated.toISOString())}</>
            ) : (
              "loading…"
            )}
          </span>
          <div className="w-64">
            <SymbolSearch onSelect={setSymbol} placeholder="jump to any symbol…" />
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[220px_1fr_300px]">
        {/* LEFT: watchlist */}
        <Panel title="Watchlist" className="xl:h-fit">
          {watchLoading ? (
            <div className="figure animate-pulse py-6 text-center text-xs text-ink-400">loading…</div>
          ) : (
            <div className="space-y-0.5">
              {watchlist.map((row) => (
                <button
                  key={row.symbol}
                  onClick={() => setSymbol(row.symbol)}
                  className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs transition-colors ${
                    symbol === row.symbol ? "bg-ink-800 text-amber-signal" : "text-ink-100 hover:bg-ink-800/50"
                  }`}
                >
                  <span className="figure">{row.symbol}</span>
                  <span className="flex items-center gap-1.5">
                    <span className="figure text-ink-400">{fmt.num(row.price, 2)}</span>
                    <span className={`figure w-14 text-right ${row.changePct >= 0 ? "text-gain" : "text-loss"}`}>
                      {fmt.pct(row.changePct, 1)}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </Panel>

        {/* CENTER: chart */}
        <Panel
          title={`${symbol} · ${range.label}`}
          right={
            <div className="flex items-center gap-2">
              <span
                className={`rounded border px-1.5 py-0.5 text-[9px] uppercase tracking-widest ${
                  isLive ? "border-gain text-gain" : "border-ink-800 text-ink-400"
                }`}
              >
                {isLive ? "live" : "placeholder"}
              </span>
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
            </div>
          }
        >
          <div className="mb-2 flex flex-wrap items-baseline gap-3">
            <span className="figure text-xl text-ink-100">{fmt.num(last.c, 2)}</span>
            <span className={`figure text-sm ${change >= 0 ? "text-gain" : "text-loss"}`}>
              {change >= 0 ? "+" : ""}
              {fmt.num(change, 2)} ({fmt.pct(changePct, 2)})
            </span>
            <Link href={`/stock/${symbol}`} className="text-[10px] uppercase tracking-widest text-ink-400 hover:text-amber-signal">
              full research page →
            </Link>
          </div>
          {chartLoading ? (
            <div className="figure animate-pulse py-16 text-center text-sm text-ink-400">loading chart…</div>
          ) : (
            <>
              <CandlestickChart
                candles={candles}
                buyZone={setup.buyZone}
                stopLoss={setup.stopLoss}
                profitTarget={setup.profitTarget}
                height={340}
              />
              <VolumeChart candles={candles} height={60} />
              <div className="mt-2 flex flex-wrap gap-4 text-[10px] text-ink-400">
                <span><span className="mr-1 inline-block h-2 w-4 rounded-sm bg-amber-signal/20 align-middle" />entry zone</span>
                <span><span className="mr-1 inline-block h-0.5 w-4 bg-loss align-middle" />stop loss</span>
                <span><span className="mr-1 inline-block h-0.5 w-4 bg-gain align-middle" />profit target</span>
              </div>
            </>
          )}
        </Panel>

        {/* RIGHT: decision */}
        <Panel title="EdgeLab Decision" right={<PreviewBadge />}>
          <div className="space-y-3">
            {decision && (
              <div className={`rounded border px-3 py-2 text-center ${ACTION_TONE[decision.action]}`}>
                <div className="figure text-lg tracking-widest">{ACTION_LABEL[decision.action]}</div>
              </div>
            )}
            {decisionError && !decision && (
              <p className="text-[10px] text-ink-400">Couldn&apos;t reach the decision engine.</p>
            )}
            {decision && <p className="text-xs leading-relaxed text-ink-100">{decision.why}</p>}
            <div className="border-t border-ink-800 pt-3">
              <div className="mb-1 text-[10px] uppercase tracking-widest text-ink-400">
                trend · <Term term="confidence">confidence</Term>
              </div>
              <div className="flex items-center gap-2">
                <span className={`figure text-sm ${setup.bias === "long" ? "text-gain" : "text-loss"}`}>
                  {setup.bias === "long" ? "Bullish" : "Bearish"}
                </span>
                <ConfidenceStamp level={setup.confidenceLevel} size="sm" />
                <span className="figure text-xs text-ink-100">{fmt.pct(setup.confidence, 0)}</span>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 border-t border-ink-800 pt-3 text-sm">
              <Stat label={<Term term="entry zone">entry low</Term>} value={fmt.num(setup.buyZone[0], 2)} />
              <Stat label={<Term term="entry zone">entry high</Term>} value={fmt.num(setup.buyZone[1], 2)} />
              <Stat label={<Term term="stop loss">stop</Term>} value={fmt.num(setup.stopLoss, 2)} tone="loss" />
              <Stat label={<Term term="profit target">target</Term>} value={fmt.num(setup.profitTarget, 2)} tone="gain" />
            </div>
            {decision && decision.invalidation_conditions[0] && (
              <p className="border-t border-ink-800 pt-3 text-[10px] leading-relaxed text-ink-400">
                Invalidates if {decision.invalidation_conditions[0].replace(/^Setup invalidates if /, "")}
              </p>
            )}
          </div>
        </Panel>
      </div>

      {/* BOTTOM: order ticket + positions */}
      <div className="grid gap-4 md:grid-cols-[320px_1fr]">
        <OrderTicket symbol={symbol} lastPrice={last.c} onFilled={refreshPositions} />
        <Panel title={positions ? `${positions.length} open position${positions.length === 1 ? "" : "s"}` : "Positions"}>
          {positionsError ? (
            <ErrorBox error={positionsError} />
          ) : positions === null ? (
            <div className="figure animate-pulse text-sm text-ink-400">loading…</div>
          ) : positions.length === 0 ? (
            <div className="py-6 text-center text-sm text-ink-400">No open positions.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-ink-800 text-left text-[10px] uppercase tracking-widest text-ink-400">
                    <th className="py-1.5 pr-4 font-normal">symbol</th>
                    <th className="py-1.5 pr-4 font-normal">qty</th>
                    <th className="py-1.5 pr-4 font-normal">avg entry</th>
                    <th className="py-1.5 pr-4 font-normal">current</th>
                    <th className="py-1.5 pr-4 font-normal">unrealized P/L</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => {
                    const pl = Number(p.unrealized_pl);
                    return (
                      <tr key={p.symbol} className="border-b border-ink-800/50 last:border-0 cursor-pointer hover:bg-ink-800/30" onClick={() => setSymbol(p.symbol)}>
                        <td className="figure py-1.5 pr-4 text-amber-signal">{p.symbol}</td>
                        <td className="figure py-1.5 pr-4">{p.qty}</td>
                        <td className="figure py-1.5 pr-4">{fmt.num(Number(p.avg_entry_price), 2)}</td>
                        <td className="figure py-1.5 pr-4">{fmt.num(Number(p.current_price), 2)}</td>
                        <td className={`figure py-1.5 pr-4 ${pl >= 0 ? "text-gain" : "text-loss"}`}>
                          {fmt.signed(pl, 2)} ({fmt.pct(Number(p.unrealized_plpc), 1)})
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

function OrderTicket({ symbol, lastPrice, onFilled }: { symbol: string; lastPrice: number; onFilled: () => void }) {
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [orderType, setOrderType] = useState<"market" | "limit">("market");
  const [qty, setQty] = useState("1");
  const [limitPrice, setLimitPrice] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<PaperOrder | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setConfirming(false);
    setResult(null);
  }, [symbol, side, qty, orderType, limitPrice]);

  const qtyNum = Number(qty) || 0;
  const refPrice = orderType === "limit" ? Number(limitPrice) || lastPrice : lastPrice;
  const estimatedCost = refPrice != null ? refPrice * qtyNum : null;
  const canSubmit = qtyNum > 0 && (orderType === "market" || Number(limitPrice) > 0) && !submitting;

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const order = await api.submitPaperOrder({
        symbol,
        side,
        qty: qtyNum,
        order_type: orderType,
        limit_price: orderType === "limit" ? Number(limitPrice) : undefined,
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

  return (
    <Panel title={`Order · ${symbol}`}>
      <div className="space-y-3">
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
        <input
          type="number"
          min="0"
          step="1"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          placeholder="quantity"
          className="figure w-full rounded border border-ink-800 bg-ink-950 px-3 py-1.5 text-sm text-ink-100 focus:border-amber-signal focus:outline-none"
        />
        {orderType === "limit" && (
          <input
            type="number"
            min="0"
            step="0.01"
            value={limitPrice}
            onChange={(e) => setLimitPrice(e.target.value)}
            placeholder={fmt.num(lastPrice, 2)}
            className="figure w-full rounded border border-ink-800 bg-ink-950 px-3 py-1.5 text-sm text-ink-100 focus:border-amber-signal focus:outline-none"
          />
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
            <div className="figure text-sm text-ink-100">
              {side} {qtyNum} {symbol} · {orderType}
              {orderType === "limit" && <> @ {fmt.num(Number(limitPrice), 2)}</>}
            </div>
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
                className="flex-1 rounded border border-gain bg-gain/10 py-1.5 text-xs uppercase tracking-widest text-gain hover:bg-gain/20 disabled:cursor-not-allowed disabled:opacity-40"
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
