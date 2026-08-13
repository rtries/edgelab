"use client";
/** Connections: broker + signal-source status, in plain language — no
 * API-key terminology exposed unless the user needs to copy something.
 *
 * Broker status is inferred from whether the paper-account endpoint
 * answers (same Alpaca keys the rest of the app already uses — there
 * is no separate "connect broker" flow yet, this just surfaces the
 * state honestly rather than pretending a connect button exists).
 *
 * TradingView: no real webhook intake endpoint exists yet (see the
 * product pivot notes) — this card is clearly marked "coming soon"
 * rather than showing a fake URL/token, per the same
 * never-fake-functionality rule as the AI setup badges.
 */
import { useEffect, useState } from "react";
import { Panel } from "@/components/ui";
import { api } from "@/lib/api";

export default function ConnectionsPage() {
  const [brokerStatus, setBrokerStatus] = useState<"checking" | "connected" | "error">("checking");

  useEffect(() => {
    api
      .paperAccount()
      .then(() => setBrokerStatus("connected"))
      .catch(() => setBrokerStatus("error"));
  }, []);

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

      <Panel title="TradingView">
        <div className="space-y-2">
          <div className="text-sm text-ink-100">Send alerts from TradingView into EdgeLab</div>
          <p className="max-w-xl text-xs leading-relaxed text-ink-400">
            Not built yet. When it lands, it&apos;ll work through TradingView&apos;s supported alert-webhook
            feature (TradingView doesn&apos;t offer a general trading API, and EdgeLab won&apos;t automate the
            TradingView website or ask for your TradingView password) — an alert fires, EdgeLab checks it against
            your risk rules, and only then places a paper order. A TradingView alert will never directly become an
            order.
          </p>
          <span className="inline-block rounded border border-ink-800 px-2 py-1 text-[10px] uppercase tracking-widest text-ink-400">
            coming soon
          </span>
        </div>
      </Panel>
    </div>
  );
}
