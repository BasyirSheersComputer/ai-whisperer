"""Background tasks.

Milestone 1: process_inbound_message simply echoes the lead's text back,
proving the receive → store → respond → send loop end-to-end.
Milestone 2 replaces the echo with the intent classifier + LLM responder.
"""
import logging

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Conversation, Lead, Message, MessageDirection
from app.services.whatsapp import WhatsAppClient
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="process_inbound_message", bind=True, max_retries=3, default_retry_delay=10)
def process_inbound_message(self, message_id: str) -> str | None:
    db = SessionLocal()
    try:
        msg = db.get(Message, message_id)
        if msg is None or msg.direction != MessageDirection.inbound:
            logger.warning("Message %s not found or not inbound; skipping", message_id)
            return None

        convo = db.get(Conversation, msg.conversation_id)
        lead = db.get(Lead, convo.lead_id)

        if lead.opted_out_at is not None:
            logger.info("Lead %s opted out; no reply", lead.id)
            return None

        # --- M1 echo behaviour (replaced by LLM pipeline in M2) ---
        reply_body = f"Echo: {msg.body}" if msg.body else "Echo: (non-text message received)"

        client = WhatsAppClient()
        wamid = client.send_text(lead.phone_e164, reply_body)

        out = Message(
            conversation_id=convo.id,
            direction=MessageDirection.outbound,
            body=reply_body,
            wamid=wamid,
            msg_type="text",
        )
        db.add(out)
        db.commit()
        return out.id
    except Exception as exc:  # pragma: no cover - retry path
        db.rollback()
        logger.exception("process_inbound_message failed for %s", message_id)
        raise self.retry(exc=exc) from exc
    finally:
        db.close()
