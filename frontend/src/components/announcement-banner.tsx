"use client";
/** Dismissible tester announcement — shown once per announcement id
 * (tracked in localStorage, nothing server-side per-user). Content is
 * hand-edited in backend/app/api/v1/announcement.py, not a CMS. */
import { useEffect, useState } from "react";
import { api, type Announcement } from "@/lib/api";

const DISMISS_KEY = "edgelab_dismissed_announcement";

export function AnnouncementBanner() {
  const [announcement, setAnnouncement] = useState<Announcement | null>(null);
  const [dismissed, setDismissed] = useState(true); // default hidden until we know it's new
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    api
      .announcement()
      .then((a) => {
        setAnnouncement(a);
        setDismissed(typeof window !== "undefined" && localStorage.getItem(DISMISS_KEY) === a.id);
      })
      .catch(() => {});
  }, []);

  if (!announcement || dismissed) return null;

  function dismiss() {
    if (!announcement) return;
    localStorage.setItem(DISMISS_KEY, announcement.id);
    setDismissed(true);
  }

  return (
    <div className="mb-4 rounded-md border border-amber-signal/60 bg-amber-signal/5 p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-widest text-amber-signal">{announcement.date}</div>
          <div className="mt-0.5 text-ink-100">{announcement.title}</div>
        </div>
        <div className="flex shrink-0 gap-2 text-[10px] uppercase tracking-widest">
          <button onClick={() => setExpanded((v) => !v)} className="text-ink-400 hover:text-amber-signal">
            {expanded ? "less" : "details"}
          </button>
          <button onClick={dismiss} className="text-ink-400 hover:text-amber-signal">
            dismiss
          </button>
        </div>
      </div>

      {expanded && (
        <div className="mt-3 space-y-3 border-t border-amber-signal/20 pt-3 text-xs leading-relaxed text-ink-400">
          <div>
            <div className="mb-1 uppercase tracking-widest text-ink-100">What changed</div>
            <ul className="list-disc space-y-1 pl-4">
              {announcement.changed.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
          <div>
            <div className="mb-1 uppercase tracking-widest text-ink-100">Needs your attention</div>
            <ul className="list-disc space-y-1 pl-4">
              {announcement.needs_attention.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
          <div>
            <div className="mb-1 uppercase tracking-widest text-ink-100">The goal</div>
            <p>{announcement.goal}</p>
          </div>
        </div>
      )}
    </div>
  );
}
