"use client";
/** Symbol search box with local autocomplete. Any typed symbol can be
 * submitted directly (Enter) — suggestions are just a convenience over
 * @/lib/tickers, not a validation gate. */
import { useMemo, useRef, useState } from "react";
import { KNOWN_TICKERS } from "@/lib/tickers";

export function SymbolSearch({
  onSelect,
  placeholder = "search a stock…",
  autoFocus = false,
}: {
  onSelect: (symbol: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const matches = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return [];
    return KNOWN_TICKERS.filter((t) => t.startsWith(q)).slice(0, 8);
  }, [query]);

  function submit(symbol: string) {
    const s = symbol.trim().toUpperCase();
    if (!s) return;
    onSelect(s);
    setQuery("");
    setOpen(false);
    inputRef.current?.blur();
  }

  return (
    <div className="relative">
      <input
        ref={inputRef}
        value={query}
        autoFocus={autoFocus}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setHighlight(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 100)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setHighlight((h) => Math.min(h + 1, matches.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight((h) => Math.max(h - 1, 0));
          } else if (e.key === "Enter") {
            submit(matches[highlight] ?? query);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        placeholder={placeholder}
        className="figure w-full rounded border border-ink-800 bg-ink-950 px-3 py-1.5 text-sm uppercase tracking-widest text-ink-100 placeholder:text-ink-400 placeholder:normal-case placeholder:tracking-normal focus:border-amber-signal focus:outline-none"
      />
      {open && matches.length > 0 && (
        <div className="absolute z-10 mt-1 w-full overflow-hidden rounded border border-ink-800 bg-ink-900 shadow-lg">
          {matches.map((m, i) => (
            <button
              key={m}
              onMouseDown={() => submit(m)}
              className={`figure block w-full px-3 py-1.5 text-left text-xs uppercase tracking-widest ${
                i === highlight ? "bg-ink-800 text-amber-signal" : "text-ink-100 hover:bg-ink-800"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
