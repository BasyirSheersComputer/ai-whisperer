# PDPA Compliance Runbook

Operational procedures under the Personal Data Protection Act 2010 as amended by
the Personal Data Protection (Amendment) Act 2024 (in force Jan–Jun 2025).
The agency acts as a **data processor** for client businesses (controllers); the
2024 amendments impose direct security obligations on processors.

## Roles

The agency must appoint a **Data Protection Officer**, notify the Commissioner of
the appointment, and publish the DPO contact email. Each client tenant records its
own DPO/owner contact in `tenants.dpo_contact`. Keep both current.

## Consent management (continuous)

Every lead carries a `consent_basis`, attestor, and timestamp, written at import and
visible in `audit_log` (`consent_attestation` events). Imports without a plausible
prior-relationship basis are rejected at the API. The client signs a contract clause
attesting their lists are first-party data. Opt-outs are processed in seconds,
multilingual (EN/BM/ZH), terminal, audited, and enforced at three layers: the
conversation engine, campaign dispatch, and manual staff sends.

## Data subject rights requests

Access/portability: `GET /api/v1/tenants/{t}/leads/{id}/export` returns the full
record and transcript; deliver to the requester within 21 days. Erasure:
`DELETE /api/v1/tenants/{t}/leads/{id}` hard-deletes the lead, conversations,
messages, bookings, and campaign rows, leaving only an audit stub. Log the request
date and completion date in the audit trail (automatic).

## Breach response (72-hour clock)

1. **Detect & contain** — rotate credentials (Meta tokens, DB, admin token), pause
   all campaigns (`POST .../campaigns/{id}/pause` per tenant or set channels inactive).
2. **Assess** — scope from `audit_log` and DB: whose data, what fields, what window.
3. **Notify the Commissioner** within **72 hours** of awareness via the PDP
   notification channel (pdp.gov.my), including nature, scope, and mitigation.
4. **Notify affected individuals** within **7 days** of the Commissioner notification
   if the breach risks significant harm (contact data + conversation content normally
   qualifies). Notify via the affected tenants (controllers) — coordinate wording.
5. **Notify affected client businesses** immediately regardless of thresholds —
   they are the controllers and carry their own obligations.
6. **Post-mortem** — document cause, fix, and prevention; retain for audit.

Penalties for non-compliance: up to RM1,000,000 and/or 3 years imprisonment.

## Security posture (standing)

Per-tenant WABA isolation; secrets in env/encrypted columns, never in git; webhook
HMAC validation; admin APIs behind bearer token; audit logging of consent, opt-out,
DSR, handoff, booking, and campaign-pause events. Host in AWS ap-southeast-5
(Malaysia) or ap-southeast-1 (Singapore); the amended cross-border regime is
risk-based, but in-country hosting is the cleanest answer to client due diligence.

## Retention

Default: lead and conversation data is retained while the client contract is active.
On contract end, export tenant data to the client and erase within 30 days
(`DELETE` per lead, or drop the tenant row set). PDPA requires data not be kept
longer than necessary for the purpose.
