"use client";
/** Dataset detail: everything you should know before trusting a backtest. */
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, fmt, type DatasetDetail } from "@/lib/api";
import { LineChart } from "@/components/charts";
import { ErrorBox, KeyValue, Loading, Panel } from "@/components/ui";

export default function DatasetPage() {
  const { timeframe, symbol } = useParams<{ timeframe: string; symbol: string }>();
  const [d, setD] = useState<DatasetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.dataset(timeframe, symbol).then(setD).catch((e) => setError(String(e)));
  }, [timeframe, symbol]);
  if (error) return <ErrorBox error={error} />;
  if (!d) return <Loading label={`loading ${symbol}`} />;
  const ok = d.integrity === "verified";
  return (
    <div className="space-y-4">
      <h1 className="figure text-lg">{d.symbol} · {d.timeframe}</h1>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Identity & integrity">
          <KeyValue
            rows={[
              ["fingerprint", <span key="f" className="text-xs">{d.fingerprint}</span>],
              ["integrity", <span key="i" className={ok ? "text-gain" : "text-loss"}>{d.integrity}</span>],
              ["provider / sources", d.sources.join(", ") || "—"],
              ["adjustment", <span key="a" className="text-xs">{d.adjustment}</span>],
              ["calendar", d.calendar],
              ["corporate actions", <span key="c" className="text-xs">{d.corporate_actions}</span>],
            ]}
          />
        </Panel>
        <Panel title="Coverage">
          <KeyValue
            rows={[
              ["rows", String(d.coverage.rows)],
              ["start", fmt.time(d.coverage.start)],
              ["end", fmt.time(d.coverage.end)],
              ["missing sessions", d.missing_sessions.length === 0 ? "none" : `${d.missing_sessions.length}`],
              ["missing intraday bars", String(d.missing_intraday_bars)],
            ]}
          />
          {d.missing_sessions.length > 0 && (
            <div className="figure mt-2 max-h-32 overflow-y-auto text-[10px] text-loss">
              {d.missing_sessions.map((m) => <div key={m}>{m}</div>)}
            </div>
          )}
        </Panel>
      </div>
      <Panel title="Close — last 300 bars (raw)">
        <LineChart series={d.preview_close} />
      </Panel>
    </div>
  );
}
