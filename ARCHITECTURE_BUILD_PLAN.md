# AI Lead Reactivation Agent — Architecture & Build Plan (Kuala Lumpur Edition)

**Companion to:** `AILeadReactivationAgent_PRD.md`
**Date:** 12 June 2026
**Decisions locked:** WhatsApp-first · Python/FastAPI · Agency model first · KL/Malaysia market

---

## 1. Why the PRD Must Be Adapted for Kuala Lumpur

The PRD was written for the US market (SMS-only, A2P 10DLC, Twilio). Three facts about Malaysia force a redesign of the channel layer — and conveniently, all three push toward the same answer: **WhatsApp-first**.

### 1.1 The SMS booking-link flow is illegal in Malaysia

Since **1 September 2024**, MCMC requires telcos to block all business SMS containing URLs, phone numbers, or requests for personal information. The business exemption ended 31 August 2024. The PRD's Phase 4 ("AI provides a booking link" via SMS) cannot work here. Sender IDs must also be pre-registered with SSM company registration documents.

### 1.2 WhatsApp is how KL actually communicates

WhatsApp penetration in Malaysia is ~90%+ of internet users. A gym in Bangsar or a dental clinic in TTDI already runs its business on WhatsApp — customers expect it, and a WhatsApp message from a known business feels normal where an SMS now reads as scam-adjacent (Malaysians have been heavily conditioned by MCMC anti-scam campaigns to distrust SMS). WhatsApp also gives us: clickable links, rich media, read receipts, interactive buttons/lists (great for booking flows), and free-form replies within the 24-hour customer service window.

### 1.3 PDPA 2024 amendments raise the compliance stakes

The Personal Data Protection (Amendment) Act 2024 came into force in stages Jan–Jun 2025:

- Direct marketing requires **prior consent** from the data subject.
- Maximum fines raised to **RM1,000,000** and/or 3 years imprisonment.
- Mandatory **breach notification**: Commissioner within 72 hours, affected individuals within 7 days if significant harm risk.
- Both controllers (the client business) and **processors (us — this matters for the agency model)** must appoint a **Data Protection Officer** and comply directly with security obligations.

**Implication:** lead ingestion must capture and verify consent provenance, not just check an opt-out flag. This is a product feature, not a checkbox — "PDPA-safe reactivation" is a selling point to KL business owners who are vaguely terrified of the new law.

### 1.4 WhatsApp's own anti-cold-outreach rules

Meta requires documented opt-in before business-initiated messages. Business-initiated contact must use **pre-approved message templates**; unsolicited blasts tank the number's quality rating and get it throttled or banned. Marketing templates are also subject to per-user frequency capping by Meta.

**Implication for product positioning:** this is *not* a cold-outreach tool. It is a **dormant-database reactivation** tool for leads who previously gave the business their number and consent (enquiry forms, walk-in sign-ups, past customers). That framing is simultaneously the PDPA-compliant one, the Meta-compliant one, and the PRD's actual stated use case. Lean into it.

---

## 2. KL Market Positioning

### 2.1 Target verticals (beachhead)

Pick verticals dense in KL/Klang Valley with high lead value, dormant databases, and existing WhatsApp habits:

| Vertical | Examples | Typical dormant DB | Avg. customer value |
|---|---|---|---|
| Fitness | Boutique gyms, MMA/yoga studios (Bangsar, Mont Kiara, Damansara) | Trial sign-ups, expired members | RM150–300/mo memberships |
| Aesthetics & wellness | Med spas, hair clinics, dental (Bukit Bintang, Mid Valley area) | Consultation enquiries | RM500–5,000/treatment |
| Healthcare-adjacent | Chiropractors, physio, TCM | Old patient lists | RM100–250/session |
| Home services | Aircon servicing (the KL equivalent of HVAC), renovation, plumbing | Quote requests | RM150–2,000/job |
| Education | Tuition centres, enrichment, driving schools | Enquiry lists, past students | RM200–600/mo |
| Automotive | Car detailing, workshops, tint shops | Service history | RM200–1,500/job |

Note the localisation: "HVAC" → aircon servicing; "roofers" → renovation/waterproofing contractors. Seasonality hooks differ too — CNY, Raya, Deepavali, year-end school holidays, and "new year new me" January gym pushes are the KL promo calendar.

### 2.2 Language & tone (the real moat)

KL leads reply in **English, Bahasa Malaysia, Manglish, and Chinese (simplified)** — often mixed mid-sentence ("Eh still got promo ah?"). The agent must:

- Detect language per-message and reply in kind.
- Handle Manglish naturally (lah/lor/ah particles, "can or not", "how much ah") without parodying it.
- Default per-tenant: business sets primary language(s); LLM mirrors the lead.

A US-built competitor cannot do this well. This is the defensible KL positioning.

### 2.3 Pricing & packaging (agency model)

- Setup fee: RM1,500–3,000 (covers WABA setup, KB building, consent audit of their database).
- Retainer: RM800–2,500/mo per location, tiered by lead volume.
- Optional performance kicker: RM X per booked appointment that shows.
- Cost basis: Meta marketing template ≈ a few sen–RM0.30/message to MY numbers (MYR billing since Apr 2026); utility templates and all in-window replies far cheaper or free. A 1,000-lead reactivation campaign costs the agency under ~RM300 in messaging — margins are excellent.

### 2.4 Go-to-market sequence

1. 2–3 design partners (free/cheap pilot) from different verticals to build template libraries and case studies ("We recovered 34 expired members for a Bangsar gym in 3 weeks").
2. Standardise per-vertical playbooks (message sequences, FAQs, offer structures).
3. Sell via the case studies to vertical lookalikes across Klang Valley, then JB/Penang.

---

## 3. Revised Channel Strategy

**Primary:** WhatsApp Business Cloud API (direct with Meta, or via BSP).

- Each tenant gets their **own WABA + display number** (or onboards their existing business number). Own-number-per-tenant isolates quality ratings — one client's bad list can't get another client banned.
- Business-initiated reactivation → **approved template messages** (utility where justifiable, marketing otherwise).
- Lead replies → opens **24-hour customer service window** → free-form LLM conversation, links allowed, interactive buttons for booking.
- Window expiry mid-conversation → re-engage with a utility template ("You were asking about X — still want the slot Tuesday 3pm?").

**Secondary (Phase 2+):** SMS fallback via a local-compliant provider for leads without WhatsApp (rare in KL) — no links, "reply YES" CTAs only, registered sender ID.

**Provider choice:** Start with **Meta Cloud API directly** (free API access, pay per message) rather than a BSP like SleekFlow/respond.io/Wati — we're building the conversation layer ourselves, so a BSP adds cost without value. Use a BSP only if WABA approval friction becomes a bottleneck during onboarding.

---

## 4. System Architecture

### 4.1 High-level diagram

```
                        ┌──────────────────────────────────────────────┐
                        │                 Meta WhatsApp                │
                        │              Cloud API (per WABA)            │
                        └──────┬───────────────────────▲───────────────┘
                       webhooks│                       │send API
                               ▼                       │
┌──────────┐   ┌───────────────────────────────────────┴──────────────┐
│  Admin   │   │                  FastAPI Backend                     │
│ Dashboard├──▶│  /webhooks/whatsapp   /api/v1/* (tenants, leads,     │
│ (React)  │   │  campaigns, conversations, kb, bookings, reports)    │
└──────────┘   └──────┬──────────────┬──────────────┬─────────────────┘
                      │              │              │
                      ▼              ▼              ▼
               ┌────────────┐ ┌────────────┐ ┌─────────────────┐
               │ PostgreSQL │ │   Redis    │ │  Celery Workers │
               │ (all data, │ │ queue +    │ │ outbound drip · │
               │ JSONB convo│ │ rate limit │ │ LLM replies ·   │
               │ logs, RLS) │ │ + locks    │ │ scheduled jobs  │
               └────────────┘ └────────────┘ └───┬─────────┬───┘
                                                 │         │
                                          ┌──────▼───┐ ┌───▼──────────┐
                                          │ Claude   │ │ Integrations │
                                          │ API      │ │ Cal.com/     │
                                          │ (LLM)    │ │ Calendly ·   │
                                          └──────────┘ │ Zapier/Make ·│
                                                        │ Email alerts │
                                                        └──────────────┘
```

### 4.2 Stack decisions (with rationale)

| Layer | Choice | Rationale / PRD deviation |
|---|---|---|
| API | **Python 3.12 + FastAPI** | Per PRD option A; best LLM tooling; async-native for webhook fan-in |
| DB | **PostgreSQL 16 only** (JSONB for convo logs) | PRD suggests Postgres + Mongo — at this scale a second DB is pure operational overhead. JSONB covers unstructured logs; revisit only past ~10M messages |
| Queue | **Redis + Celery** (Celery Beat for cron) | Per PRD; drip scheduling, throttling, retries |
| LLM | **Claude API** (Sonnet for conversations, Haiku for intent classification) | Two-tier: cheap fast classifier gates the expensive conversationalist |
| Messaging | **Meta WhatsApp Cloud API** | Replaces Twilio SMS (see §1, §3) |
| Calendar | **Cal.com** (self-hostable, free, API-first) primary; Calendly + Google Calendar connectors next | Nylas is overkill/cost for v1; KL SMBs mostly have *no* scheduling tool — we provision Cal.com for them as part of setup |
| CRM connect | CSV upload first; **generic inbound/outbound webhooks** (Zapier/Make-compatible) second | Per PRD; many KL SMBs' "CRM" is an Excel sheet — CSV is the real v1 integration |
| Dashboard | React + Vite admin panel (agency-internal) | Agency model: one dashboard, all tenants; client-facing portal later |
| Hosting | Single VPS/container host to start (e.g., AWS ap-southeast-5 **Malaysia region** or ap-southeast-1 Singapore) | Data residency story for PDPA-nervous clients; trivial cost |
| Observability | Structured logs + Sentry + a messages/bookings metrics table | Booked-appointment count is the only KPI clients buy on |

### 4.3 Multi-tenancy

Agency model, but **tenant-scoped from day one** (PRD Milestone 5 pulled forward into the schema, not the UI):

- Every table carries `tenant_id`; enforce with Postgres **Row-Level Security** plus application-level scoping.
- Per-tenant: WABA credentials, phone number, system prompt, knowledge base, offer config, throttle limits, quiet hours, language defaults.
- Secrets (WABA tokens, API keys) in encrypted columns or a secrets manager, never plaintext.

---

## 5. Data Model (core tables)

```sql
tenants            id, name, slug, industry, status, timezone (default Asia/Kuala_Lumpur),
                   languages text[], quiet_hours jsonb, dpo_contact, created_at

tenant_channels    id, tenant_id, type (whatsapp|sms), waba_id, phone_number_id,
                   display_number, access_token_enc, quality_rating, status

business_profiles  id, tenant_id, business_name, core_offer, booking_url,
                   faq_md text, pricing_md text, hours jsonb, current_promos jsonb

leads              id, tenant_id, name, phone_e164 (+60...), language_pref,
                   source, consent_basis (enum: existing_customer|enquiry_form|
                   walk_in|imported_attested), consent_attested_by, consent_date,
                   last_contact_date, status (enum: imported|queued|contacted|
                   engaged|qualified|booked|confirmed|showed|opted_out|dead|
                   handed_off), opted_out_at, created_at
                   UNIQUE (tenant_id, phone_e164)

campaigns          id, tenant_id, name, template_name, template_lang, offer_text,
                   drip_config jsonb (batch_size, interval, daily_cap),
                   start_at, status, stats jsonb

campaign_leads     campaign_id, lead_id, scheduled_at, sent_at, wamid, status,
                   error

conversations      id, tenant_id, lead_id, channel_id, state (state machine),
                   window_expires_at, assigned_to_human bool, last_message_at

messages           id, conversation_id, direction (in|out), body, wamid,
                   template_name, msg_type, llm_meta jsonb (model, intent,
                   confidence, tokens), delivery_status, created_at

bookings           id, tenant_id, lead_id, conversation_id, calendar_provider,
                   external_event_id, slot_start, slot_end, status
                   (offered|booked|confirmed|showed|no_show|cancelled)

handoffs           id, conversation_id, reason, alerted_via, resolved_at

audit_log          id, tenant_id, actor, action, entity, payload jsonb, at
                   -- PDPA: consent changes, opt-outs, data exports/deletions
```

Conversation transcripts live in `messages` (Postgres, JSONB for `llm_meta`) — no Mongo.

---

## 6. Conversation State Machine

```
IMPORTED ──consent ok──▶ QUEUED ──drip──▶ CONTACTED
                                              │ inbound reply (24h window opens)
                                              ▼
                              ┌────────── ENGAGED ◀────────────┐
              intent:negative │     intent:question/positive   │ window re-open
              or "stop/henti" │            │                   │ via utility
                              ▼            ▼                   │ template
                         OPTED_OUT     QUALIFIED ──ready──▶ BOOKING_OFFERED
                         (ack + CRM        │                    │ slot picked
                          update,          │ complex Q or       ▼
                          suppress         │ human requested  BOOKED ──confirm──▶ CONFIRMED
                          forever)         ▼                    │                  │
                                      HANDED_OFF                │ no reply 48h     ▼
                                      (alert staff,             ▼               SHOWED /
                                       pause AI)            STALE → nudge ×1    NO_SHOW
```

Rules:

- **Intent classification first** (Haiku, structured output): `positive | question | negative_soft | opt_out | request_human | unclear`. Opt-out keywords short-circuit before any LLM generation — including Malay/Chinese forms: *stop, berhenti, tak nak, tak mahu, jangan mesej, unsubscribe, 不要, 停*.
- **Opt-out is terminal and tenant-global**: suppressed in `leads.opted_out_at` + a phone-level suppression check at send time; acknowledgment sent once; logged to `audit_log`.
- **Max nudges:** initial template + at most 2 follow-ups, then `DEAD`. Never message between tenant quiet hours (default 9pm–9am MYT) or on the lead's opted-out number.
- **Window management:** free-form replies only while `window_expires_at > now()`; otherwise queue a utility template re-opener.
- **Handoff:** pause automation, email/WhatsApp-alert tenant staff with transcript link, resume only by human action.

---

## 7. LLM Layer

### 7.1 Two-model pipeline per inbound message

1. **Classifier (Haiku):** intent + detected language + extracted entities (preferred time, objection type). Cheap, fast, structured JSON.
2. **Responder (Sonnet):** only invoked for `positive/question/unclear`; generates the reply with full context injection.

### 7.2 Context injection (per PRD §4, extended)

```
System prompt (per tenant) =
  persona + boundaries
  + business profile (name, offer, FAQ, pricing, hours, promos)
  + language policy (mirror lead; supported: EN/BM/Manglish/ZH)
  + current goal (drive to booking; booking link/slots injected live)
  + hard rules (below)

Per message =
  lead name + consent source + conversation history (last N turns)
  + current state + live calendar slots if state ≥ QUALIFIED
```

### 7.3 Persona rules — one deliberate PRD deviation

PRD rule 1 says "never disclose that you are an AI." **Recommend amending to: don't volunteer it, never deny it.** If a lead asks "is this a bot?", the agent says it's the business's automated assistant and offers a human. Reasons: Malaysian consumers increasingly probe for scams (MCMC-conditioned skepticism — denying AI status reads as scam behaviour and triggers blocks/reports, which damage the WABA quality rating); deceptive denial creates PDPA/consumer-protection exposure for clients; and honesty costs almost nothing in conversion when the assistant is useful. Final call is yours — flagged because it's a one-line prompt change with outsized risk implications.

Other rules per PRD: brevity (WhatsApp norm: 1–3 short lines, not 160-char SMS limits), no invented pricing/medical claims, no medical advice for the clinic verticals (extra guardrail: aesthetics/chiro tenants get a stricter prompt that defers all clinical questions to consultation booking), out-of-KB questions → "let me check with the team" → handoff.

### 7.4 Per-vertical prompt packs

Ship tenant onboarding with vertical presets (gym, dental, aesthetics, aircon, tuition): tone, common objections ("so expensive lah" → value framing, not discounting beyond configured floor), seasonal hooks (Raya promo, CNY closing dates), and BM/EN template pairs.

---

## 8. Compliance Architecture (PDPA + MCMC + Meta)

Built-in, not bolted on — this is sales collateral for KL:

1. **Consent gate at ingestion:** every imported lead must carry a `consent_basis`; CSV import requires the client to attest source ("these are people who enquired/transacted with us"), recorded with attestor + timestamp in `audit_log`. Leads with no plausible basis are rejected from campaigns.
2. **Opt-out engineering:** multilingual keyword detection, terminal suppression list, ack message, CRM webhook out. Honour within seconds, not hours.
3. **Data subject rights endpoints:** export-my-data and delete-my-data per lead (PDPA access/erasure + new portability right), executable from the dashboard.
4. **Breach readiness:** encrypted secrets, RLS, access logging; documented 72-hour Commissioner / 7-day individual notification runbook; appoint a DPO for the agency entity (2024 amendments apply to processors directly).
5. **Meta hygiene:** template pre-approval workflow in dashboard; per-tenant quality-rating monitor (webhook field) with auto-pause of campaigns if rating drops; default throttle ~50 msgs/hour/tenant (PRD's number, also sane for Meta tier ramp: new numbers start at 250 business-initiated conversations/day and scale up with quality).
6. **Data residency:** host in AWS Malaysia (ap-southeast-5) or Singapore; PDPA's amended cross-border regime is risk-based, but "your customer data stays in Malaysia" is an easy yes for nervous clients.

---

## 9. Build Milestones (revised from PRD §5)

Sequenced to demo value earliest; each milestone ends runnable.

### M1 — Foundation + WhatsApp echo (Week 1–2)
FastAPI skeleton, Postgres + Alembic migrations (tenant-scoped schema from §5), Redis/Celery wiring, Docker Compose dev env. Meta Cloud API: webhook verify + receive, send text + template. Deliverable: message a test WABA number, get an echo. *(PRD M1, Twilio→Meta.)*

### M2 — Brain: classifier + responder + state machine (Week 3–4)
Haiku intent classifier (incl. BM/ZH opt-out lexicon), Sonnet responder with context injection, conversation state machine, 24-h window tracking, opt-out terminal path, handoff alert (email). Deliverable: full simulated conversation from hook to booking-intent on a seeded tenant. *(PRD M2.)*

### M3 — Leads in: CSV ingestion + consent gate (Week 5)
CSV upload endpoint with validation (E.164 +60 normalisation, dedupe), consent attestation flow, inbound webhook for Zapier/Make, lead lifecycle statuses. Deliverable: upload a 500-row messy real-world CSV; clean leads queued. *(PRD M3.)*

### M4 — Outbound engine: campaigns + drip + throttle (Week 6–7)
Campaign CRUD, template management (submit/approve via Meta API), Celery Beat drip scheduler (batch size, hourly cap, quiet hours MYT), retry/dead-letter handling, quality-rating circuit breaker. Deliverable: 50-lead pilot campaign end-to-end against a real (consenting) test list. *(PRD M4.)*

### M5 — Booking: Cal.com integration (Week 8)
Live availability fetch, in-chat slot offer (WhatsApp interactive list), booking creation, confirmation template, reminder template T-24h (cheap no-show insurance — high impact in KL services), no-show tracking. Deliverable: lead books and receives confirmation without human touch. *(PRD M4's calendar half, promoted to its own milestone — it's the money step.)*

### M6 — Agency dashboard + multilingual polish (Week 9–10)
React admin: tenant onboarding wizard (profile, KB, templates, channel connect), live conversation viewer with human-takeover, campaign stats (sent → replied → qualified → booked → showed funnel), handoff inbox. Manglish/BM conversation QA pass with real KL testers. Deliverable: onboard design-partner client #1 without touching the DB. *(PRD M5; multi-tenant schema already exists, this is the UI.)*

### M7 — Pilot & hardening (Week 11–12)
2–3 KL design partners live. Sentry, metrics, PDPA runbook docs, prompt iteration from real transcripts, case-study data collection.

**Per PRD instruction:** I'll ask for confirmation before starting each milestone.

---

## 10. Key Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Client uploads scraped/bought lists → WABA ban + PDPA exposure | High (SMB behaviour) | Consent attestation gate; contract clause; reject lists with no plausible basis; per-tenant number isolation |
| WABA quality rating drops mid-campaign | Medium | Quality webhook → auto-pause circuit breaker; conservative throttle; warm-up ramp on new numbers |
| Meta template rejections delay launches | Medium | Pre-approved per-vertical template library in EN+BM; utility-category framing where legitimate |
| LLM hallucinates pricing/medical claims | Medium | KB-only answers, strict boundary prompts, clinical-vertical hard deferral, transcript sampling QA |
| 24-h window expires before booking closes | High | Utility re-opener templates; push for booking link early in window |
| PDPA processor obligations (agency = processor) | Certain | DPO appointment, RLS + encryption, audit log, breach runbook — all in M1–M4 scope |
| Manglish/BM quality is off-brand | Medium | Per-tenant tone config; KL human QA pass in M6; few-shot examples from real (anonymised) chats |
| "Don't deny AI" vs PRD's "never disclose" | — | Flagged §7.3; owner decision before M2 prompts are finalised |

---

## 11. Open Questions (answer before M1)

1. WABA setup: will design partners onboard their **existing** WhatsApp business numbers (requires migrating the number to Cloud API — they lose the WhatsApp Business app on that number) or take a **new** dedicated number? New number is operationally simpler; existing number converts better. Recommend: new number for pilot, revisit.
2. Confirm §7.3 persona decision (AI disclosure on direct question).
3. Agency entity: is there an SSM-registered company to register WABAs and act as PDPA processor/DPO? Meta business verification needs it.
4. First design-partner vertical — gym, dental, or aesthetics? (Determines which prompt pack and template library gets built first in M2/M4.)
