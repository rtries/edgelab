# Launching for a small test group

A step-by-step guide for getting 2-3 invited people onto their own
accounts, each with fully isolated deployments, experiments, and
patterns. No public signup — you create the accounts.

## 1. Supabase — auth only

You don't need Supabase's database here, just Auth.

1. Create a project at supabase.com (or use an existing one).
2. **Project Settings → API**: copy the **Project URL**, the
   **anon public key**, and the **JWT Secret**.
3. **Authentication → Providers**: make sure Email is enabled.
4. **Authentication → Users → Add user**: create one user per tester
   (email + password, or "send invite link" if you'd rather they set
   their own password). Do this for yourself too.

That's the entire signup story — there's no signup page in the app on
purpose.

## 2. Backend — Render or Railway

The FastAPI backend needs a **persistent disk**, since deployments,
experiments, and patterns live on the filesystem, namespaced per user.

Render:
1. New → Web Service, point it at this repo, root directory `backend`.
2. Build command: `pip install -e .`
   Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Add a **persistent disk** (Render → Disks), mount it at e.g.
   `/data`, and set:
   ```
   EDGELAB_RESEARCH_ROOT=/data/research_data
   EDGELAB_DATA_ROOT=/data/data/store
   EDGELAB_OPS_ROOT=/data/ops_data
   ```
4. Environment variables:
   ```
   API_ENV=production
   AUTH_DISABLED=false
   SUPABASE_JWT_SECRET=<the JWT Secret from step 1>
   API_CORS_ORIGINS=["https://your-app.vercel.app"]
   ```
5. Deploy. Note the backend's public URL.

Railway works the same way — a service from this repo, a volume
mounted for the three `EDGELAB_*_ROOT` paths, the same env vars.

## 3. Frontend — Vercel

1. Import the repo into Vercel, root directory `frontend`.
2. Environment variables:
   ```
   NEXT_PUBLIC_API_URL=<the backend URL from step 2>
   NEXT_PUBLIC_SUPABASE_URL=<Project URL from step 1>
   NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon public key from step 1>
   ```
3. Deploy. Update `API_CORS_ORIGINS` on the backend once you know the
   final Vercel URL, and redeploy the backend.

## 4. Seed some data (optional but recommended)

Real market data makes this much more interesting for testers than the
synthetic seed data. Wire in a provider (Yahoo/Alpaca/Polygon adapters
already exist from Phase 2) and pull a few symbols into
`EDGELAB_DATA_ROOT` before anyone logs in — market data is shared
across all users by design, so you only need to do this once.

## 5. Send invites

Give each tester the Vercel URL and the email/password (or invite
link) you set up for them in step 1. First login lands them on an
empty dashboard — their own experiments, deployments, and patterns,
completely separate from yours and each other's.

## What "collecting data" means here, concretely

Everything a tester does — experiments they run, deployments they
create, paper trades, notes — lives under their own
`{research,ops}_data/{user_id}/` folder on the backend's disk. To look
at what they've been doing:

- **Quick look**: sign in as them (or ask them to share an experiment
  id / deployment id) and browse the terminal normally.
- **Bulk look**: SSH/shell into the Render/Railway instance (or pull
  the disk contents) and read the JSON files directly — every
  experiment, deployment, and pattern record is a plain JSON file, and
  event logs are JSONL, so `jq`/`grep` work fine for a first pass.
- If you want structured analytics later (e.g. "which strategies did
  people try most"), the natural next step is a lightweight aggregation
  script over those per-user folders rather than a new subsystem —
  the data's already there, it's just not summarized yet.

## Local dev (unchanged)

Local development still works without any of this — set
`AUTH_DISABLED=true` and `API_ENV=development` in `backend/.env`, and
the API accepts every request as a fixed `dev-local` user, no Supabase
project needed. This is also what the test suite uses. **Never set
`AUTH_DISABLED=true` on a deployed instance** — `app/main.py` refuses
to start with it set unless `API_ENV=development`.
