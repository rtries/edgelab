"use client";
/** Plain-English explanations for trading terms — attached at first use,
 * not buried in a separate "Learn Trading" course. A dotted underline +
 * tooltip; experienced users can just ignore it. */
import type { ReactNode } from "react";

export const TERMS: Record<string, string> = {
  "risk/reward": "For every $1 of planned downside, this setup targets roughly that many dollars of upside.",
  "entry zone": "The price range EdgeLab considers a reasonable place to start a position for this setup.",
  "stop loss": "The price where, if reached, the setup is considered wrong and the position would be exited to limit the loss.",
  "profit target": "A price level where the setup's upside thesis is considered largely played out.",
  support: "A price level where buyers have historically stepped in.",
  resistance: "An area where sellers have historically become active.",
  confidence: "How strongly the evidence agrees with this setup — not a probability of profit, and not a guarantee.",
  "day range": "The lowest and highest price this stock has traded at during the most recent session.",
};

export function Term({ term, children }: { term: keyof typeof TERMS | string; children: ReactNode }) {
  const explanation = TERMS[term.toLowerCase()];
  if (!explanation) return <>{children}</>;
  return (
    <span className="cursor-help border-b border-dotted border-ink-400" title={explanation}>
      {children}
    </span>
  );
}
