"use client";
/** Persistent feedback entry point — present on every page so testers
 * never have to go looking for it. Captures page/symbol/browser/time
 * automatically so the report is structured, not free-text guesswork. */
import { useState } from "react";
import { usePathname } from "next/navigation";
import { api, type FeedbackCategory } from "@/lib/api";

const CATEGORIES: { value: FeedbackCategory; label: string }[] = [
  { value: "bug", label: "Bug" },
  { value: "confusing_ui", label: "Confusing UI" },
  { value: "missing_feature", label: "Missing feature" },
  { value: "suggestion", label: "Suggestion" },
  { value: "general", label: "General feedback" },
];

function symbolFromPathname(pathname: string): string | undefined {
  const m = pathname.match(/^\/stock\/([A-Za-z.]+)/);
  return m ? m[1].toUpperCase() : undefined;
}

export function FeedbackButton() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<FeedbackCategory>("general");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setCategory("general");
    setMessage("");
    setDone(false);
    setError(null);
  }

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      await api.submitFeedback({
        category,
        message,
        page: pathname,
        symbol: symbolFromPathname(pathname),
        browser: typeof navigator !== "undefined" ? navigator.userAgent : undefined,
        client_timestamp: new Date().toISOString(),
      });
      setDone(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="figure fixed bottom-4 right-4 z-40 rounded-full border border-amber-signal bg-ink-950 px-4 py-2 text-xs uppercase tracking-widest text-amber-signal shadow-lg hover:bg-amber-signal hover:text-ink-950"
      >
        send feedback
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => {
            setOpen(false);
            reset();
          }}
        >
          <div
            className="w-full max-w-md rounded-md border border-ink-800 bg-ink-900 p-4"
            onClick={(e) => e.stopPropagation()}
          >
            {done ? (
              <div className="space-y-3 text-center">
                <div className="text-sm text-gain">Thanks — feedback recorded.</div>
                <button
                  onClick={() => {
                    setOpen(false);
                    reset();
                  }}
                  className="rounded border border-ink-800 px-3 py-1.5 text-xs uppercase tracking-widest text-ink-100 hover:border-amber-signal hover:text-amber-signal"
                >
                  close
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm uppercase tracking-widest text-ink-100">Send feedback</h2>
                  <button
                    onClick={() => {
                      setOpen(false);
                      reset();
                    }}
                    className="text-ink-400 hover:text-ink-100"
                  >
                    ✕
                  </button>
                </div>

                <div className="figure text-[10px] text-ink-400">
                  page {pathname}
                  {symbolFromPathname(pathname) && <> · symbol {symbolFromPathname(pathname)}</>}
                </div>

                <div className="flex flex-wrap gap-1">
                  {CATEGORIES.map((c) => (
                    <button
                      key={c.value}
                      onClick={() => setCategory(c.value)}
                      className={`rounded border px-2 py-1 text-[10px] uppercase tracking-widest transition-colors ${
                        category === c.value
                          ? "border-amber-signal text-amber-signal"
                          : "border-ink-800 text-ink-400 hover:border-ink-400 hover:text-ink-100"
                      }`}
                    >
                      {c.label}
                    </button>
                  ))}
                </div>

                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="What happened, or what would help?"
                  rows={5}
                  className="w-full rounded border border-ink-800 bg-ink-950 p-2 text-sm text-ink-100 focus:border-amber-signal focus:outline-none"
                />

                {error && <div className="text-xs text-loss">{error}</div>}

                <button
                  disabled={message.trim().length === 0 || submitting}
                  onClick={submit}
                  className="w-full rounded border border-amber-signal py-2 text-xs uppercase tracking-widest text-amber-signal hover:bg-amber-signal hover:text-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {submitting ? "sending…" : "submit"}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
