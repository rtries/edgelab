"use client";
/** Real headlines from Alpaca's News API (via /market/news) — a plain
 * feed: headline, source, age, optional summary, symbol tags. It makes
 * no claim about what a story means for price; that would be invented.
 *
 * `symbol` may be omitted (general market news), a single symbol, or a
 * comma-separated list. `refreshMs` re-polls (paused while the tab is
 * hidden) — news changes slowly, so keep it long.
 */
import { useEffect, useState } from "react";
import { api, type NewsItem } from "@/lib/api";

function timeAgo(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (Number.isNaN(mins)) return "";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

// Headlines/URLs are third-party data — only ever link http(s).
function safeHref(url: string): string | null {
  return /^https?:\/\//i.test(url) ? url : null;
}

export function NewsFeed({
  symbol,
  limit = 8,
  refreshMs = 5 * 60_000,
  showSummary = true,
}: {
  symbol?: string;
  limit?: number;
  refreshMs?: number;
  showSummary?: boolean;
}) {
  const [items, setItems] = useState<NewsItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setError(null);
    const load = () =>
      api
        .news(symbol, limit)
        .then((r) => {
          if (cancelled) return;
          setItems(r);
          setError(null);
        })
        .catch((e) => {
          if (!cancelled) setError(String(e));
        });
    load();
    const id = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, refreshMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [symbol, limit, refreshMs]);

  if (error && !items) {
    return <p className="text-xs text-loss">Couldn&apos;t load news: {error}</p>;
  }
  if (items === null) {
    return <div className="figure animate-pulse py-4 text-sm text-ink-400">loading news…</div>;
  }
  if (items.length === 0) {
    return <p className="py-2 text-xs text-ink-400">No recent news{symbol ? ` for ${symbol}` : ""}.</p>;
  }

  return (
    <ul className="divide-y divide-ink-800/60">
      {items.map((n) => {
        const href = safeHref(n.url);
        return (
          <li key={n.id} className="py-2.5">
            {href ? (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm leading-snug text-ink-100 hover:text-amber-signal"
              >
                {n.headline}
              </a>
            ) : (
              <span className="text-sm leading-snug text-ink-100">{n.headline}</span>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] uppercase tracking-widest text-ink-400">
              <span>{n.source}</span>
              <span>·</span>
              <span title={n.created_at}>{timeAgo(n.created_at)}</span>
              {n.symbols.slice(0, 4).map((s) => (
                <span key={s} className="figure rounded-sm border border-ink-800 px-1 py-0.5 normal-case tracking-normal">
                  {s}
                </span>
              ))}
            </div>
            {showSummary && n.summary && (
              <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-ink-400">{n.summary}</p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
