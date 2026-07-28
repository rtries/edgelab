"use client";
/** Sign in only — no signup form. For 2-3 invited testers, accounts are
 * created directly in the Supabase dashboard (or via a magic-link
 * invite you send); this page just authenticates against them. */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { signIn } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const err = await signIn(email, password);
    setBusy(false);
    if (err) {
      setError(err);
      return;
    }
    router.push("/");
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <form onSubmit={submit} className="w-full max-w-xs space-y-4 rounded-md border border-ink-800 bg-ink-900 p-6">
        <div>
          <span className="figure text-sm tracking-widest text-amber-signal">EDGE</span>
          <span className="figure text-sm tracking-widest text-ink-100">LAB</span>
          <div className="text-[9px] uppercase tracking-widest text-ink-400">research terminal — sign in</div>
        </div>
        <div className="space-y-2">
          <input
            type="email"
            placeholder="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="w-full rounded border border-ink-800 bg-ink-950 px-2 py-1.5 text-sm figure placeholder:text-ink-400 focus:border-amber-signal focus:outline-none"
          />
          <input
            type="password"
            placeholder="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="w-full rounded border border-ink-800 bg-ink-950 px-2 py-1.5 text-sm figure placeholder:text-ink-400 focus:border-amber-signal focus:outline-none"
          />
        </div>
        {error && <p className="text-xs text-loss">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded border border-amber-signal px-3 py-1.5 text-xs uppercase tracking-widest text-amber-signal hover:bg-amber-signal/10 disabled:opacity-50"
        >
          {busy ? "signing in…" : "Sign in"}
        </button>
        <p className="text-[10px] text-ink-400">
          Invite-only — accounts are created for you. No signup here.
        </p>
      </form>
    </div>
  );
}
