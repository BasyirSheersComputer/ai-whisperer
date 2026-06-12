"""Background tasks.

M2: process_inbound_message runs the conversation orchestrator
(classifier + state machine + responder) and sends the decided reply.
"""
import logging

from app.db import SessionLocal
from app.models import Conversation, Lead, Message, MessageDirection
from app.services.conversation import _store_outbound, handle_inbound
from app.services.whatsapp import WhatsAppClient
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="process_inbound_message", bind=True, max_retries=3, default_retry_delay=10)
def process_inbound_message(self, message_id: str) -> str | None:
    db = SessionLocal()
    try:
        result = handle_inbound(db, message_id)
        if result is None or not result.get("reply"):
            db.commit()  # state changes (e.g. silence decisions) still persist
            return None

        msg = db.get(Message, message_id)
        convo = db.get(Conversation, msg.conversation_id)
        lead = db.get(Lead, convo.lead_id)

        client = WhatsAppClient()
        wamid = client.send_text(lead.phone_e164, result["reply"])
        out = _store_outbound(db, convo, result["reply"], wamid, result.get("llm_meta"))
        db.commit()
        return out.id
    except Exception as exc:  # pragma: no cover - retry path
        db.rollback()
        logger.exception("process_inbound_message failed for %s", message_id)
        raise self.retry(exc=exc) from exc
    finally:
        db.close()
