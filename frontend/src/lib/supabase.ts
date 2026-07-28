/** Supabase browser client. Two env vars, both safe to expose to the
 * browser (the anon key is meant to be public — access control lives
 * in the JWT verification on the backend, not in this key). */
import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

if (!url || !anonKey) {
  // Loud in dev, so a missing env var doesn't silently fail every request.
  // A placeholder URL keeps createClient() from throwing during builds
  // (e.g. static prerendering) that run without real env vars configured —
  // any actual auth call against the placeholder will fail loudly at
  // runtime instead, which is the correct failure mode.
  // eslint-disable-next-line no-console
  console.warn(
    "NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY are not set — auth will not work.",
  );
}

export const supabase = createClient(
  url || "https://placeholder.invalid",
  anonKey || "placeholder-anon-key",
);
