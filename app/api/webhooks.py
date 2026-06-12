"""Meta WhatsApp Cloud API webhook endpoints."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.services.inbound import apply_account_updates, record_inbound_message
from app.services.security import verify_meta_signature
from app.workers.tasks import process_inbound_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/whatsapp")
def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    settings = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not verify_meta_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    apply_account_updates(db, payload)
    new_message_ids = record_inbound_message(db, payload)
    for message_id in new_message_ids:
        process_inbound_message.delay(message_id)

    # Always 200 quickly — Meta retries non-200s aggressively.
    return {"received": True, "queued": len(new_message_ids)}
