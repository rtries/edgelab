"use client";
/** Research notes — write down what didn't work; it's half the value. */
import { useEffect, useState } from "react";
import { api, fmt, type Note } from "@/lib/api";
import { ErrorBox, Loading, Panel, Tag } from "@/components/ui";

const inputCls =
  "w-full rounded border border-ink-800 bg-ink-950 px-2 py-1.5 text-sm placeholder:text-ink-400 focus:border-amber-signal focus:outline-none";

export default function NotesPage() {
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState("");

  const refresh = () => api.notes().then(setNotes).catch((e) => setError(String(e)));
  useEffect(() => {
    refresh();
  }, []);

  const save = async () => {
    if (!title.trim()) return;
    await api.addNote(title.trim(), body.trim(), tags.split(",").map((t) => t.trim()).filter(Boolean));
    setTitle(""); setBody(""); setTags("");
    refresh();
  };

  if (error) return <ErrorBox error={error} />;
  if (!notes) return <Loading label="loading notes" />;

  return (
    <div className="space-y-4">
      <h1 className="text-lg tracking-wide">Notes</h1>
      <Panel title="New note">
        <div className="space-y-2">
          <input className={inputCls} placeholder="title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <textarea className={`${inputCls} min-h-24`} placeholder="what did you try, what happened, what next" value={body} onChange={(e) => setBody(e.target.value)} />
          <div className="flex gap-2">
            <input className={inputCls} placeholder="tags, comma separated" value={tags} onChange={(e) => setTags(e.target.value)} />
            <button onClick={save} className="shrink-0 rounded border border-amber-signal px-4 text-xs uppercase tracking-widest text-amber-signal hover:bg-amber-signal hover:text-ink-950">
              Save note
            </button>
          </div>
        </div>
      </Panel>
      {notes.map((n) => (
        <Panel key={n.id} title={n.title} right={
          <div className="flex items-center gap-3">
            <span className="figure text-[10px] text-ink-400">{fmt.time(n.created_at)}</span>
            <button onClick={() => api.deleteNote(n.id).then(refresh)} className="text-[10px] uppercase tracking-widest text-loss hover:underline">delete</button>
          </div>
        }>
          <p className="whitespace-pre-line text-sm">{n.body || <span className="text-ink-400">—</span>}</p>
          {n.tags.length > 0 && <div className="mt-2 flex gap-1">{n.tags.map((t) => <Tag key={t}>{t}</Tag>)}</div>}
        </Panel>
      ))}
      {notes.length === 0 && <p className="text-sm text-ink-400">No notes yet.</p>}
    </div>
  );
}
