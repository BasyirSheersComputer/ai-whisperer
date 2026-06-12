# AI Lead Reactivation Agent (KL Edition)

WhatsApp-first dormant-lead reactivation for Kuala Lumpur SMBs. See
`AILeadReactivationAgent_PRD.md` (requirements) and `ARCHITECTURE_BUILD_PLAN.md`
(architecture, KL compliance, milestones).

**Status: all milestones (M1–M7) complete.** End-to-end: lead CSV ingestion with
PDPA consent gate → throttled WhatsApp template campaigns with quality circuit
breaker → LLM conversation engine (multilingual opt-out, qualification, handoff)
→ in-chat slot booking with T-24h reminders → agency admin dashboard at `/admin`.
Every external dependency (Meta, Claude, Cal.com) has a dry-run mode, so the whole
system runs locally with zero API keys. See `docs/PDPA_RUNBOOK.md` for compliance
operations.

## Quick start (local, no Docker)

Requires Python 3.10+.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate on mac/linux)
pip install -r requirements-dev.txt
copy .env.example .env           # defaults are fine for dev (dry-run on)

pytest                           # run the test suite
ruff check .                     # lint
```

Run the API (SQLite is fine for a quick look — set `DATABASE_URL=sqlite:///./dev.db` in `.env`):

```bash
python -m scripts.seed_demo      # demo tenant, phone_number_id=1234567890
uvicorn app.main:app --reload
```

Simulate a lead messaging the business (debug mode only):

```bash
curl -X POST http://localhost:8000/api/v1/simulate/inbound \
  -H "Content-Type: application/json" \
  -d '{"phone_number_id":"1234567890","from_number":"+60123456789","body":"Hi, still got promo ah?"}'
```

With `LLM_DRY_RUN=true` replies come from deterministic heuristics. For live AI
replies set `GEMINI_API_KEY` and `LLM_DRY_RUN=false` (Gemini is the default
provider: flash-lite classifies intent, flash writes replies). Anthropic is the
alternative: `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY`.

## Full stack (Docker)

```bash
docker compose up --build        # api :8000, worker, postgres :5432, redis :6379
```

## Deployment

Two supported targets — same codebase, same env vars:

- **Vercel (serverless):** `CELERY_EAGER=true`, crons replace Celery beat,
  managed Postgres (Neon/Supabase). Full guide: `docs/VERCEL_DEPLOY.md`.
- **Docker (full stack):** `docker compose up` — API + Celery worker/beat +
  Postgres + Redis. For VPS/Fly.io/Railway/AWS ap-southeast-5.

## Connecting a real WABA (when ready)

1. Meta Business verification with your SSM-registered entity.
2. Create a WhatsApp Business App; note App Secret, Access Token, Phone Number ID.
3. Set webhook URL to `https://<host>/webhooks/whatsapp` with your `META_VERIFY_TOKEN`.
4. Fill `.env`, set `WHATSAPP_DRY_RUN=false`.
5. Insert a `tenant_channels` row with the real `phone_number_id`.

## Layout

```
app/
  main.py            app factory
  config.py          env settings
  db.py              engine/session
  models.py          tenant-scoped schema (plan §5)
  api/               webhooks, simulator, health
  services/          whatsapp client, signature check, inbound pipeline,
                     lexicon (multilingual opt-out), llm, prompts, conversation
  workers/           celery app + tasks
scripts/seed_demo.py
tests/
```

## Milestones

- [x] **M1** Foundation + WhatsApp echo
- [x] **M2** Intent classifier + LLM responder + state machine
- [x] **M3** CSV ingestion + consent gate + PDPA DSR endpoints
- [x] **M4** Campaigns, drip scheduler, throttle, quality circuit breaker
- [x] **M5** Cal.com booking flow + reminders
- [x] **M6** Agency dashboard (`/admin`) + management APIs
- [x] **M7** PDPA runbook, optional Sentry, hardening

Schema migrations: the schema is created via `create_all` on startup. Introduce
Alembic before the first schema change against a live production database.

## Key endpoints

| Area | Endpoint |
|---|---|
| Webhook (Meta) | `GET/POST /webhooks/whatsapp` |
| Simulator (debug) | `POST /api/v1/simulate/inbound` |
| Leads | `POST .../leads/import-csv`, `POST .../leads`, `GET .../leads` |
| PDPA DSR | `GET .../leads/{id}/export`, `DELETE .../leads/{id}` |
| Campaigns | `POST .../campaigns`, `/enqueue`, `/start`, `/pause`, `GET .../campaigns/{id}` |
| Bookings | `GET .../bookings`, `PATCH .../bookings/{id}` |
| Admin | `/admin` UI; `/api/v1/admin/*` (tenants, funnel, conversations, takeover, send, handoffs) |
