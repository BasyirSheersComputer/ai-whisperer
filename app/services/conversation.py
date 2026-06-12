"""Conversation orchestrator (plan §6) — the M2 brain.

For each inbound message:
1. Deterministic opt-out check (lexicon, no LLM) → terminal suppression + ack.
2. Deterministic human-request check → handoff.
3. LLM classify → state transition → LLM respond (or handoff on [HANDOFF]).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AuditLog,
    BusinessProfile,
    Conversation,
    ConversationState,
    Handoff,
    Lead,
    LeadStatus,
    Message,
    MessageDirection,
    Tenant,
)
from app.services import lexicon, llm
from app.services.prompts import build_history, build_responder_system

logger = logging.getLogger(__name__)

OPT_OUT_ACK = (
    "Noted, we won't message you again. Thank you! / "
    "Baik, kami tidak akan menghantar mesej lagi. Terima kasih!"
)
HANDOFF_REPLY = "Sure — let me get someone from the team to follow up with you here shortly!"


def _store_outbound(db: Session, convo: Conversation, body: str, wamid: str | None, llm_meta: dict | None = None) -> Message:
    out = Message(
        conversation_id=convo.id,
        direction=MessageDirection.outbound,
        body=body,
        wamid=wamid,
        msg_type="text",
        llm_meta=llm_meta,
    )
    db.add(out)
    convo.last_message_at = datetime.now(timezone.utc)
    return out


def _audit(db: Session, tenant_id: str, action: str, entity: str, payload: dict) -> None:
    db.add(AuditLog(tenant_id=tenant_id, actor="system", action=action, entity=entity, payload=payload))


def _handle_opt_out(db: Session, lead: Lead, convo: Conversation) -> dict:
    now = datetime.now(timezone.utc)
    lead.opted_out_at = now
    lead.status = LeadStatus.opted_out
    convo.state = ConversationState.opted_out
    _audit(db, lead.tenant_id, "opt_out", "lead", {"lead_id": lead.id, "at": now.isoformat()})
    return {"action": "opt_out_ack", "reply": OPT_OUT_ACK}


def _handle_handoff(db: Session, lead: Lead, convo: Conversation, reason: str) -> dict:
    convo.state = ConversationState.handed_off
    convo.assigned_to_human = True
    lead.status = LeadStatus.handed_off
    db.add(Handoff(conversation_id=convo.id, reason=reason, alerted_via="log"))
    _audit(db, lead.tenant_id, "handoff", "conversation", {"conversation_id": convo.id, "reason": reason})
    # M2: alert is logged; M6 wires email/dashboard notification.
    logger.warning("HANDOFF tenant=%s convo=%s reason=%s", lead.tenant_id, convo.id, reason)
    return {"action": "handoff", "reply": HANDOFF_REPLY}


_STATE_AFTER_INTENT = {
    "positive": ConversationState.qualified,
    "question": ConversationState.engaged,
    "negative_soft": ConversationState.engaged,
    "unclear": ConversationState.engaged,
}


def handle_inbound(db: Session, message_id: str) -> dict | None:
    """Decide and store the response for one inbound message.

    Returns {"action", "reply", "llm_meta"} or None when no reply should be sent.
    The caller (Celery task) performs the actual WhatsApp send.
    """
    msg = db.get(Message, message_id)
    if msg is None or msg.direction != MessageDirection.inbound:
        return None

    convo = db.get(Conversation, msg.conversation_id)
    lead = db.get(Lead, convo.lead_id)

    # Already opted out → never respond, whatever the conversation state.
    # (Campaign-side suppression is additionally checked at send time in M4.)
    if lead.opted_out_at is not None:
        return None

    # Human owns this conversation → AI stays silent.
    if convo.assigned_to_human:
        logger.info("Conversation %s is human-assigned; AI silent", convo.id)
        return None

    text = msg.body or ""

    # 1. Compliance short-circuits (deterministic, multilingual, no LLM).
    if lexicon.is_opt_out(text):
        return _handle_opt_out(db, lead, convo)
    if lexicon.is_human_request(text):
        return _handle_handoff(db, lead, convo, reason=f"Lead requested human: {text[:200]}")

    # 2. Classify.
    classification = llm.classify(text)
    if classification.intent == "opt_out":
        return _handle_opt_out(db, lead, convo)
    if classification.intent == "request_human":
        return _handle_handoff(db, lead, convo, reason=f"Classifier: human request: {text[:200]}")

    # 3. State transition.
    new_state = _STATE_AFTER_INTENT.get(classification.intent, ConversationState.engaged)
    # Never regress from a further-along state.
    progression = [
        ConversationState.contacted,
        ConversationState.engaged,
        ConversationState.qualified,
        ConversationState.booking_offered,
        ConversationState.booked,
        ConversationState.confirmed,
    ]
    if convo.state in progression and progression.index(new_state) > progression.index(convo.state):
        convo.state = new_state
    if classification.intent == "positive" and lead.status in (LeadStatus.engaged, LeadStatus.contacted):
        lead.status = LeadStatus.qualified

    # 4. Generate reply.
    tenant = db.get(Tenant, lead.tenant_id)
    profile = db.scalar(select(BusinessProfile).where(BusinessProfile.tenant_id == tenant.id))
    if profile is None:
        return _handle_handoff(db, lead, convo, reason="No business profile configured")

    system_prompt = build_responder_system(tenant, profile, lead)
    history_rows = db.scalars(
        select(Message).where(Message.conversation_id == convo.id).order_by(Message.created_at)
    ).all()
    history = build_history(history_rows, get_settings().max_history_turns)

    reply = llm.respond(system_prompt, history, classification, profile.booking_url)

    # Out-of-knowledge-base sentinel from the responder prompt.
    if reply.startswith("[HANDOFF]"):
        return _handle_handoff(db, lead, convo, reason=f"Out of KB: {text[:200]}")

    llm_meta = {
        "intent": classification.intent,
        "language": classification.language,
        "entities": classification.entities,
        "dry_run": True if not get_settings().anthropic_api_key or get_settings().llm_dry_run else False,
    }
    if classification.intent == "positive" and profile.booking_url and profile.booking_url in reply:
        convo.state = ConversationState.booking_offered

    return {"action": "reply", "reply": reply, "llm_meta": llm_meta}
