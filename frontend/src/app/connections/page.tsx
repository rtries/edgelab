"use client";
/** Connections: broker + signal-source status, in plain language — no
 * API-key terminology exposed unless the user needs to copy something.
 *
 * Broker status is inferred from whether the paper-account endpoint
 * answers (same Alpaca keys the rest of the app already uses — there
 * is no separate "connect broker" flow yet, this just surfaces the
 * state honestly rather than pretending a connect button exists).
 *
 * TradingView: real webhook intake now — see app/api/v1/tradingview.py.
 * Paper only, and a signal only acts if EdgeLab's own Decision Engine
 * currently agrees (an alert alone is never sufficient).
 */
import { useEffect, useState } from "react";
import { ErrorBox, Panel } from "@/components/ui";
import { api } from "@/lib/api";

export default function ConnectionsPage() {
  const [brokerStatus, setBrokerStatus] = useState<"checking" | "connected" | "error">("checking");

  const [linked, setLinked] = useState<boolean | null>(null);
  const [autoTrade, setAutoTrade] = useState(false);
  const [linkCode, setLinkCode] = useState<string | null>(null);
  const [codeMinutes, setCodeMinutes] = useState<number | null>(null);
  const [telegramError, setTelegramError] = useState<string | null>(null);

  const [tvUrl, setTvUrl] = useState<string | null>(null);
  const [tvExample, setTvExample] = useState<string | null>(null);
  const [tvError, setTvError] = useState<string | null>(null);
  const [tvCopied, setTvCopied] = useState(false);

  useEffect(() => {
    api
      .paperAccount()
      .then(() => setBrokerStatus("connected"))
      .catch(() => setBrokerStatus("error"));
  }, []);

  function refreshTelegramStatus() {
    api
      .telegramStatus()
      .then((s) => {
        setLinked(s.linked);
        setAutoTrade(s.auto_trade);
      })
      .catch((e) => setTelegramError(String(e)));
  }
  useEffect(refreshTelegramStatus, []);

  function getCode() {
    setTelegramError(null);
    api
      .telegramLinkCode()
      .then((r) => {
        setLinkCode(r.code);
        setCodeMinutes(r.expires_in_minutes);
      })
      .catch((e) => setTelegramError(String(e)));
  }

  function getWebhookUrl() {
    setTvError(null);
    api
      .tradingviewWebhookUrl()
      .then((r) => {
        setTvUrl(r.url);
        setTvExample(r.example_message);
      })
      .catch((e) => setTvError(String(e)));
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg tracking-wide">Connections</h1>
        <p className="text-xs text-ink-400">Where EdgeLab gets data and sends orders.</p>
      </div>

      <Panel title="Broker">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm text-ink-100">Alpaca</div>
            <div className="text-xs text-ink-400">Paper trading — fake money, real order matching.</div>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span
              className={`h-2 w-2 rounded-full ${
                brokerStatus === "connected" ? "bg-gain" : brokerStatus === "error" ? "bg-loss" : "bg-ink-400"
              }`}
            />
            <span
              className={
                brokerStatus === "connected" ? "text-gain" : brokerStatus === "error" ? "text-loss" : "text-ink-400"
              }
            >
              {brokerStatus === "checking" ? "checking…" : brokerStatus === "connected" ? "Connected" : "Not reachable"}
            </span>
          </div>
        </div>
      </Panel>

      <Panel title="Telegram">
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-ink-100">Check your agent and toggle paper auto-trade from chat</div>
              <div className="text-xs text-ink-400">Paper trading only — Telegram can never place a real-money order.</div>
            </div>
            {linked != null && (
              <div className="flex items-center gap-2 text-xs">
                <span className={`h-2 w-2 rounded-full ${linked ? "bg-gain" : "bg-ink-400"}`} />
                <span className={linked ? "text-gain" : "text-ink-400"}>{linked ? "Linked" : "Not linked"}</span>
              </div>
            )}
          </div>

          {telegramError && <ErrorBox error={telegramError} />}

          {linked ? (
            <div className="text-xs text-ink-400">
              Auto-trade is currently{" "}
              <span className={autoTrade ? "text-gain" : "text-ink-100"}>{autoTrade ? "ON" : "OFF"}</span> — toggle
              it from the bot with <span className="figure text-ink-100">/on</span> or{" "}
              <span className="figure text-ink-100">/off</span>.
            </div>
          ) : (
            <div className="space-y-2">
              <ol className="list-decimal space-y-1 pl-4 text-xs text-ink-400">
                <li>Get a link code below</li>
                <li>Open the EdgeLab bot on Telegram</li>
                <li>
                  Send <span className="figure text-ink-100">/link CODE</span> using the code you got
                </li>
              </ol>
              {linkCode ? (
                <div className="flex items-center gap-2 rounded border border-ink-800 bg-ink-950 px-3 py-2">
                  <span className="figure text-lg tracking-widest text-amber-signal">{linkCode}</span>
                  <span className="text-xs text-ink-400">expires in {codeMinutes} min</span>
                  <button
                    onClick={() => navigator.clipboard?.writeText(`/link ${linkCode}`)}
                    className="ml-auto rounded border border-ink-800 px-2 py-1 text-[10px] uppercase tracking-widest text-ink-100 hover:border-amber-signal hover:text-amber-signal"
                  >
                    copy /link command
                  </button>
                </div>
              ) : (
                <button
                  onClick={getCode}
                  className="rounded border border-ink-800 px-3 py-1.5 text-xs uppercase tracking-widest text-ink-100 hover:border-amber-signal hover:text-amber-signal"
                >
                  Get link code
                </button>
              )}
            </div>
          )}
        </div>
      </Panel>

      <Panel title="TradingView">
        <div className="space-y-3">
          <div>
            <div className="text-sm text-ink-100">Send alerts from TradingView into EdgeLab</div>
            <p className="mt-1 max-w-xl text-xs leading-relaxed text-ink-400">
              Works with any symbol you trade, not just EdgeLab&apos;s watchlist. Paper only — an alert fires,
              EdgeLab checks it against its own current read on that symbol and your risk rules, and only then
              places a paper order. An alert never directly becomes an order.
            </p>
          </div>

          {tvError && <ErrorBox error={tvError} />}

          {tvUrl ? (
            <div className="space-y-2">
              <div>
                <div className="mb-1 text-[10px] uppercase tracking-widest text-ink-400">1. Webhook URL — paste into TradingView&apos;s alert &quot;Webhook URL&quot; field</div>
                <div className="flex items-center gap-2 rounded border border-ink-800 bg-ink-950 px-3 py-2">
                  <span className="figure truncate text-xs text-ink-100">{tvUrl}</span>
                  <button
                    onClick={() => {
                      navigator.clipboard?.writeText(tvUrl);
                      setTvCopied(true);
                    }}
                    className="ml-auto shrink-0 rounded border border-ink-800 px-2 py-1 text-[10px] uppercase tracking-widest text-ink-100 hover:border-amber-signal hover:text-amber-signal"
                  >
                    {tvCopied ? "copied" : "copy"}
                  </button>
                </div>
              </div>
              <div>
                <div className="mb-1 text-[10px] uppercase tracking-widest text-ink-400">2. Alert message — paste into TradingView&apos;s alert &quot;Message&quot; field</div>
                <div className="rounded border border-ink-800 bg-ink-950 px-3 py-2">
                  <code className="figure text-xs text-ink-100">{tvExample}</code>
                </div>
                <p className="mt-1 text-[10px] text-ink-400">
                  Change &quot;side&quot; to &quot;sell&quot; for a sell alert, and replace {"{{ticker}}"} with a fixed symbol if you&apos;d rather not rely on TradingView&apos;s placeholder.
                </p>
              </div>
            </div>
          ) : (
            <button
              onClick={getWebhookUrl}
              className="rounded border border-ink-800 px-3 py-1.5 text-xs uppercase tracking-widest text-ink-100 hover:border-amber-signal hover:text-amber-signal"
            >
              Get webhook URL
            </button>
          )}
        </div>
      </Panel>
    </div>
  );
}
