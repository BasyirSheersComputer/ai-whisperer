# AI Lead Reactivation Agent (KL Edition)

WhatsApp-first dormant-lead reactivation for Kuala Lumpur SMBs. See
`AILeadReactivationAgent_PRD.md` (requirements) and `ARCHITECTURE_BUILD_PLAN.md`
(architecture, KL compliance, milestones).

**Status: Milestone 1 complete** — FastAPI backend, tenant-scoped schema, Meta
WhatsApp Cloud API webhooks (verify + signed receive), dry-run send client,
Celery echo pipeline, inbound simulator.

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

The worker echoes the message back (logged, since `WHATSAPP_DRY_RUN=true`).

## Full stack (Docker)

```bash
docker compose up --build        # api :8000, worker, postgres :5432, redis :6379
```

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
  services/          whatsapp client, signature check, inbound pipeline
  workers/           celery app + tasks (M1: echo; M2: LLM)
scripts/seed_demo.py
tests/
```

## Milestones

- [x] **M1** Foundation + WhatsApp echo
- [ ] **M2** Intent classifier + LLM responder + state machine
- [ ] **M3** CSV ingestion + consent gate (+ Alembic migrations)
- [ ] **M4** Campaigns, drip scheduler, throttle, quality circuit breaker
- [ ] **M5** Cal.com booking flow
- [ ] **M6** Agency dashboard + multilingual polish
- [ ] **M7** KL pilot & hardening
