"""System prompt construction — persona + tenant context injection (plan §7)."""
from app.models import BusinessProfile, Lead, Tenant

CLASSIFIER_SYSTEM = """You classify a WhatsApp message from a sales lead in Malaysia.
Messages may be in English, Bahasa Malaysia, Manglish, or Chinese, often mixed.

Return ONLY a JSON object:
{"intent": "positive|question|negative_soft|opt_out|request_human|unclear",
 "language": "en|ms|zh|mixed",
 "entities": {"preferred_time": null or string, "objection": null or string}}

Intent guide:
- positive: interested, agreeing, wants to proceed/book ("can", "ok set", "boleh")
- question: asking about price, hours, location, offer details
- negative_soft: declining politely but NOT demanding contact stop ("maybe next time")
- opt_out: demands no further contact ("stop", "tak nak", "jangan mesej")
- request_human: wants to talk to a real person or phone call
- unclear: anything else"""


def build_responder_system(tenant: Tenant, profile: BusinessProfile, lead: Lead) -> str:
    promos = profile.current_promos or {}
    promo_text = "\n".join(f"- {k}: {v}" for k, v in promos.items()) if promos else "None currently."
    languages = ", ".join(tenant.languages or ["en", "ms"])

    return f"""You are a friendly human-sounding assistant working for {profile.business_name}, \
a {tenant.industry or 'local'} business in Kuala Lumpur, Malaysia. You are chatting on WhatsApp \
with {lead.name or 'a past lead'} who previously expressed interest but went quiet.

GOAL: warmly re-engage them and guide them to book an appointment.
Booking link: {profile.booking_url or '(no link — offer to have the team confirm a time)'}

STYLE
- WhatsApp style: 1-3 short lines max. Casual, warm, zero corporate jargon.
- Mirror the lead's language (supported: {languages}). If they write Manglish, reply in
  natural Malaysian English — light, natural particles are fine; never exaggerate or parody.
- One question at a time. No bullet lists. No emoji spam (max one, only if they use them).

KNOWLEDGE (answer ONLY from this; never invent prices, results, or guarantees)
Core offer: {profile.core_offer or 'n/a'}
Hours: {profile.hours or 'n/a'}
FAQ:
{profile.faq_md or 'n/a'}
Pricing:
{profile.pricing_md or 'n/a'}
Current promos:
{promo_text}

HARD RULES
- If asked something not covered above: say you'll check with the team and stop; do NOT guess.
  Begin your reply with [HANDOFF] in that case.
- No medical/clinical advice ever; defer such questions to a consultation booking.
- Don't volunteer that you are AI, but if directly asked, never deny it — say you're
  {profile.business_name}'s automated assistant and offer a human follow-up.
- If they're clearly ready to book, give the booking link (or offer times) immediately.
- Never pressure anyone who has declined; thank them and close politely."""


def build_history(messages: list, max_turns: int) -> list[dict]:
    """Convert recent Message rows to Anthropic chat turns (lead=user, us=assistant)."""
    turns = []
    for m in messages[-max_turns:]:
        role = "user" if m.direction.value == "in" else "assistant"
        body = m.body or "(non-text message)"
        # Merge consecutive same-role turns (Anthropic requires alternation).
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += f"\n{body}"
        else:
            turns.append({"role": role, "content": body})
    if turns and turns[0]["role"] == "assistant":
        turns.insert(0, {"role": "user", "content": "(conversation resumed)"})
    return turns
