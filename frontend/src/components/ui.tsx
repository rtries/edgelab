"use client";
/** Terminal UI kit. The confidence stamp is deliberately loud — it is the
 * product's honesty rendered as a component, and it follows an experiment
 * everywhere its numbers appear. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { FeedbackButton } from "@/components/feedback-button";

export function Panel({
  title,
  right,
  children,
  className = "",
}: {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-md border border-ink-800 bg-ink-900 ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between border-b border-ink-800 px-3 py-2">
          <h2 className="text-xs font-medium uppercase tracking-widest text-ink-400">{title}</h2>
          <div>{right}</div>
        </header>
      )}
      <div className="p-3">{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  tone = "neutral",
  hint,
}: {
  label: ReactNode;
  value: string;
  tone?: "neutral" | "gain" | "loss" | "amber";
  hint?: string;
}) {
  const color =
    tone === "gain"
      ? "text-gain"
      : tone === "loss"
        ? "text-loss"
        : tone === "amber"
          ? "text-amber-signal"
          : "text-ink-100";
  return (
    <div className="min-w-24" title={hint}>
      <div className="text-[10px] uppercase tracking-widest text-ink-400">{label}</div>
      <div className={`figure text-lg ${color}`}>{value}</div>
    </div>
  );
}

const STAMP: Record<string, string> = {
  strong: "border-gain text-gain",
  moderate: "border-amber-signal text-amber-signal",
  weak: "border-loss text-loss",
  insufficient: "border-loss/70 bg-loss/10 text-loss",
};

export function ConfidenceStamp({ level, size = "md" }: { level: string | null | undefined; size?: "sm" | "md" }) {
  if (!level) return <span className="text-ink-400">—</span>;
  return (
    <span
      className={`figure inline-block -rotate-1 rounded border-2 uppercase tracking-widest ${STAMP[level] ?? "border-ink-400 text-ink-400"} ${
        size === "sm" ? "px-1.5 py-0 text-[10px]" : "px-2.5 py-0.5 text-xs"
      }`}
    >
      {level}
    </span>
  );
}

/** Marks any placeholder AI output — never let a mocked number pass as
 * real analysis without this attached right next to it. */
export function PreviewBadge({ className = "" }: { className?: string }) {
  return (
    <span
      className={`figure inline-flex cursor-help items-center gap-1 rounded border border-amber-signal/60 px-1.5 py-0.5 text-[9px] uppercase tracking-widest text-amber-signal ${className}`}
      title="This analysis is currently generated using placeholder logic while the production scoring engine is integrated."
    >
      preview analysis
    </span>
  );
}

export function Tag({ children }: { children: ReactNode }) {
  return (
    <span className="figure rounded-sm border border-ink-800 bg-ink-950 px-1.5 py-0.5 text-[10px] text-ink-400">
      {children}
    </span>
  );
}

export function KeyValue({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-6 border-b border-ink-800/60 py-1.5 last:border-0">
          <dt className="text-ink-400">{k}</dt>
          <dd className="figure text-right break-all">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function DataTable({
  columns,
  rows,
}: {
  columns: string[];
  rows: ReactNode[][];
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-ink-800 text-left text-[10px] uppercase tracking-widest text-ink-400">
            {columns.map((c) => (
              <th key={c} className="py-1.5 pr-4 font-normal">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, i) => (
            <tr key={i} className="border-b border-ink-800/50 last:border-0 hover:bg-ink-800/30">
              {cells.map((cell, j) => (
                <td key={j} className="figure py-1.5 pr-4">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && (
        <div className="py-6 text-center text-sm text-ink-400">nothing here yet</div>
      )}
    </div>
  );
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: string[];
  active: string;
  onChange: (t: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1 border-b border-ink-800">
      {tabs.map((t) => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className={`px-3 py-1.5 text-xs uppercase tracking-widest transition-colors ${
            active === t
              ? "border-b-2 border-amber-signal text-amber-signal"
              : "text-ink-400 hover:text-ink-100"
          }`}
        >
          {t}
        </button>
      ))}
    </div>
  );
}

export function Loading({ label = "loading" }: { label?: string }) {
  return <div className="figure animate-pulse p-6 text-sm text-ink-400">{label}…</div>;
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div className="rounded border border-loss/50 bg-loss/10 p-4 text-sm">
      <div className="mb-1 font-medium text-loss">Couldn&apos;t reach the server</div>
      <div className="figure text-xs text-ink-400">{error}</div>
      <div className="mt-2 text-xs text-ink-400">
        This is usually temporary — try refreshing in a moment. If it keeps happening, send feedback with the
        button in the corner.
      </div>
    </div>
  );
}

// A short, always-visible list plus a collapsible "Research Lab" group —
// the quant-research pages are real and stay one click away, but a new
// user's first impression is a trading app, not a research console.
const PRIMARY_NAV: { href: string; label: string }[] = [
  { href: "/", label: "Dashboard" },
  { href: "/scanner", label: "Scanner" },
  { href: "/markets", label: "Markets" },
  { href: "/trading", label: "Trading" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/morning", label: "Morning Brief" },
];

const RESEARCH_NAV: { href: string; label: string }[] = [
  { href: "/strategies", label: "Strategies" },
  { href: "/experiments", label: "Experiments" },
  { href: "/compare", label: "Compare" },
  { href: "/optimization", label: "Optimization" },
  { href: "/walkforward", label: "Walk Forward" },
  { href: "/montecarlo", label: "Monte Carlo" },
  { href: "/reports", label: "Reports" },
  { href: "/deployments", label: "Deployments" },
  { href: "/monitoring", label: "Live Monitoring" },
  { href: "/edge-health", label: "Edge Health" },
  { href: "/research-queue", label: "Research Queue" },
  { href: "/patterns", label: "Pattern Library" },
  { href: "/datasets", label: "Datasets" },
  { href: "/history", label: "History" },
  { href: "/notes", label: "Notes" },
];

function NavLink({ href, label, pathname }: { href: string; label: string; pathname: string }) {
  const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
  return (
    <Link
      href={href}
      className={`block px-4 py-1.5 text-xs uppercase tracking-widest transition-colors ${
        active
          ? "border-l-2 border-amber-signal bg-ink-900 text-amber-signal"
          : "border-l-2 border-transparent text-ink-400 hover:text-ink-100"
      }`}
    >
      {label}
    </Link>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const researchActive = RESEARCH_NAV.some((item) => pathname.startsWith(item.href));
  const [researchOpen, setResearchOpen] = useState(researchActive);
  // Once a tester is inside a research page, keep the group open even if
  // they haven't manually expanded it.
  const showResearch = researchOpen || researchActive;

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-44 shrink-0 flex-col border-r border-ink-800 bg-ink-950">
        <Link href="/" className="block border-b border-ink-800 px-4 py-3">
          <span className="figure text-sm tracking-widest text-amber-signal">EDGE</span>
          <span className="figure text-sm tracking-widest text-ink-100">LAB</span>
          <div className="text-[9px] uppercase tracking-widest text-ink-400">trading platform</div>
        </Link>
        <nav className="flex-1 overflow-y-auto py-2">
          {PRIMARY_NAV.map((item) => (
            <NavLink key={item.href} href={item.href} label={item.label} pathname={pathname} />
          ))}

          <button
            onClick={() => setResearchOpen((v) => !v)}
            className="mt-2 flex w-full items-center justify-between border-l-2 border-transparent px-4 py-1.5 text-[10px] uppercase tracking-widest text-ink-400 hover:text-ink-100"
          >
            <span>Research Lab</span>
            <span>{showResearch ? "−" : "+"}</span>
          </button>
          {showResearch &&
            RESEARCH_NAV.map((item) => (
              <NavLink key={item.href} href={item.href} label={item.label} pathname={pathname} />
            ))}
        </nav>
        <ShellFooter />
      </aside>
      <main className="min-w-0 flex-1 p-4">{children}</main>
      <FeedbackButton />
    </div>
  );
}

function ShellFooter() {
  const { session, signOut } = useAuth();
  return (
    <div className="border-t border-ink-800 p-3 text-[9px] leading-relaxed text-ink-400">
      {session?.user.email && (
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="figure truncate" title={session.user.email}>{session.user.email}</span>
          <button onClick={() => signOut()} className="shrink-0 uppercase tracking-widest text-ink-400 hover:text-amber-signal">
            sign out
          </button>
        </div>
      )}
      Simulated results under stated assumptions. No claim of future profitability.
    </div>
  );
}
