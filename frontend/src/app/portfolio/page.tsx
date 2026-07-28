"use client";
/** Portfolio: honest placeholder until Phase 5 (paper trading). */
import Link from "next/link";
import { Panel } from "@/components/ui";

export default function PortfolioPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Portfolio</h1>
      <Panel title="No live portfolio exists yet — and that is the correct state">
        <p className="max-w-2xl text-sm leading-relaxed text-ink-400">
          EdgeLab currently runs research on historical data. There is no live or paper account
          connected, so this page will not pretend to have positions. Paper trading through a broker
          adapter is Phase 5; it unlocks only after strategies survive validation — see the{" "}
          <Link href="/experiments" className="text-amber-signal hover:underline">experiment registry</Link>{" "}
          for how that is going. Simulated equity curves live with their experiments, clearly labeled,
          not here dressed up as a portfolio.
        </p>
      </Panel>
    </div>
  );
}
