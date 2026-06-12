# Deploying to Vercel

The app runs on Vercel as serverless functions. Two architectural notes:

1. **No Celery worker/beat on Vercel.** Set `CELERY_EAGER=true` — inbound messages
   are processed inline in the webhook request, and `vercel.json` crons replace
   Celery beat (`/api/v1/internal/dispatch` every minute, `/reminders` every 5).
   Note: minute-level crons require a Vercel Pro plan; Hobby allows daily crons only.
2. **Managed Postgres required.** Use Neon or Supabase (Singapore region —
   closest to KL) and use the **pooled** connection string.

## Supabase (configured 13 Jun 2026)

Project: **ai-whisperer** (`nllzywzonturdbhiwhvl`, region ap-southeast-2,
Postgres 17). The full 11-table schema is applied as migration
`initial_schema_m1_m7` with RLS enabled on every table (no policies — the
public REST/GraphQL surface is locked; the app connects as the postgres role,
which bypasses RLS). `create_all` on app startup is a no-op against it.

`DATABASE_URL` for Vercel (transaction pooler, port 6543 — required for
serverless):

```
postgresql+psycopg2://postgres.nllzywzonturdbhiwhvl:[DB-PASSWORD]@aws-0-ap-southeast-2.pooler.supabase.com:6543/postgres
```

Get `[DB-PASSWORD]` from Supabase Dashboard -> Project Settings -> Database
(reset it if unknown). If the pooler host differs, copy the "Transaction
pooler" string from Dashboard -> Connect and add the `+psycopg2` driver prefix.

## Steps

1. Database: done (above).
2. `vercel link` the repo (or import it in the Vercel dashboard — framework preset:
   Other; no build command needed).
3. Set environment variables (Production):

   | Var | Value |
   |---|---|
   | `DATABASE_URL` | pooled Postgres URL (with `+psycopg2` driver prefix) |
   | `CELERY_EAGER` | `true` |
   | `CRON_SECRET` | long random string (Vercel auto-sends it on cron calls) |
   | `ADMIN_TOKEN` | long random string for `/admin` |
   | `META_VERIFY_TOKEN` / `META_APP_SECRET` / `META_ACCESS_TOKEN` / `META_PHONE_NUMBER_ID` | from Meta developer console |
   | `WHATSAPP_DRY_RUN` | `true` until the WABA is verified, then `false` |
   | `ANTHROPIC_API_KEY` + `LLM_DRY_RUN=false` | for live Claude replies |
   | `CALCOM_API_KEY` + `CALENDAR_DRY_RUN=false` | for live slots |
   | `DEBUG` | `false` |

4. Deploy, then initialise the schema once:
   `curl -H "Authorization: Bearer $CRON_SECRET" https://<app>.vercel.app/api/v1/internal/init-db`
5. Point the Meta webhook at `https://<app>.vercel.app/webhooks/whatsapp`
   with your `META_VERIFY_TOKEN`.
6. Open `https://<app>.vercel.app/admin`, enter `ADMIN_TOKEN`, onboard tenant #1.

## Caveats

- Inline processing means webhook response time includes the LLM call (~1-3s);
  Meta tolerates this, but keep `maxDuration` at 60 in `vercel.json`.
- Vercel functions are stateless: anything needing steady throughput at scale
  (hundreds of msgs/min) should move to the Docker deployment (Fly.io, Railway,
  AWS ap-southeast-5) where real Celery workers run. The codebase supports both —
  it's the same env vars minus `CELERY_EAGER`.
