"""Inbound message pipeline: parse Meta webhook payloads, persist, enqueue processing."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ConsentBasis,
    Conversation,
    ConversationState,
    Lead,
    LeadStatus,
    Message,
    MessageDirection,
    TenantChannel,
)

logger = logging.getLogger(__name__)

CUSTOMER_SERVICE_WINDOW = timedelta(hours=24)


def parse_webhook_payload(payload: dict) -> tuple[list[dict], list[dict]]:
    """Extract (messages, statuses) events from a Meta webhook payload.

    Each message event dict: {phone_number_id, from_wa_id, wamid, msg_type, body, profile_name}
    Each status event dict: {wamid, status}
    """
    messages: list[dict] = []
    statuses: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                body = None
                msg_type = msg.get("type", "unknown")
                if msg_type == "text":
                    body = msg.get("text", {}).get("body")
                elif msg_type == "button":
                    body = msg.get("button", {}).get("text")
                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
                    body = reply.get("title")
                messages.append(
                    {
                        "phone_number_id": phone_number_id,
                        "from_wa_id": msg.get("from"),
                        "wamid": msg.get("id"),
                        "msg_type": msg_type,
                        "body": body,
                        "profile_name": contacts.get(msg.get("from")),
                    }
                )
            for st in value.get("statuses", []):
                statuses.append({"wamid": st.get("id"), "status": st.get("status")})
    return messages, statuses


def resolve_channel(db: Session, phone_number_id: str | None) -> TenantChannel | None:
    if not phone_number_id:
        return None
    return db.scalar(select(TenantChannel).where(TenantChannel.phone_number_id == phone_number_id))


def get_or_create_lead(db: Session, tenant_id: str, wa_id: str, profile_name: str | None) -> Lead:
    phone = f"+{wa_id.lstrip('+')}"
    lead = db.scalar(select(Lead).where(Lead.tenant_id == tenant_id, Lead.phone_e164 == phone))
    if lead is None:
        lead = Lead(
            tenant_id=tenant_id,
            name=profile_name,
            phone_e164=phone,
            source="inbound",
            consent_basis=ConsentBasis.inbound,
            consent_date=datetime.now(timezone.utc),
            status=LeadStatus.engaged,
        )
        db.add(lead)
        db.flush()
    return lead


def get_or_create_conversation(db: Session, lead: Lead, channel: TenantChannel) -> Conversation:
    convo = db.scalar(
        select(Conversation)
        .where(Conversation.lead_id == lead.id, Conversation.tenant_id == lead.tenant_id)
        .order_by(Conversation.last_message_at.desc())
    )
    if convo is None or convo.state in (ConversationState.dead, ConversationState.opted_out):
        convo = Conversation(
            tenant_id=lead.tenant_id,
            lead_id=lead.id,
            channel_id=channel.id,
            state=ConversationState.engaged,
        )
        db.add(convo)
        db.flush()
    return convo


def record_inbound_message(db: Session, payload: dict) -> list[str]:
    """Persist inbound messages + delivery statuses. Returns new inbound message IDs."""
    events, statuses = parse_webhook_payload(payload)
    new_message_ids: list[str] = []
    now = datetime.now(timezone.utc)

    for event in events:
        channel = resolve_channel(db, event["phone_number_id"])
        if channel is None:
            logger.warning("No tenant channel for phone_number_id=%s; dropping", event["phone_number_id"])
            continue
        # Idempotency: Meta retries webhooks; skip already-stored wamids.
        if event["wamid"] and db.scalar(select(Message).where(Message.wamid == event["wamid"])):
            continue

        lead = get_or_create_lead(db, channel.tenant_id, event["from_wa_id"], event["profile_name"])
        if lead.opted_out_at is not None:
            # An opted-out lead messaging us again re-opens dialogue but campaigns stay suppressed.
            logger.info("Inbound from opted-out lead %s; storing without re-engagement", lead.id)

        convo = get_or_create_conversation(db, lead, channel)
        msg = Message(
            conversation_id=convo.id,
            direction=MessageDirection.inbound,
            body=event["body"],
            wamid=event["wamid"],
            msg_type=event["msg_type"],
        )
        db.add(msg)
        convo.last_message_at = now
        convo.window_expires_at = now + CUSTOMER_SERVICE_WINDOW
        if convo.state == ConversationState.contacted:
            convo.state = ConversationState.engaged
        if lead.status in (LeadStatus.imported, LeadStatus.queued, LeadStatus.contacted):
            lead.status = LeadStatus.engaged
        db.flush()
        new_message_ids.append(msg.id)

    for st in statuses:
        if not st["wamid"]:
            continue
        out_msg = db.scalar(select(Message).where(Message.wamid == st["wamid"]))
        if out_msg is not None:
            out_msg.delivery_status = st["status"]

    db.commit()
    return new_message_ids
