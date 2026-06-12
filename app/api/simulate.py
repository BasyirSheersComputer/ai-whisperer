"""Dev-only simulator: inject an inbound WhatsApp message without a real WABA.

Equivalent of the PRD M1 'dummy endpoint to simulate a user sending an SMS',
adapted for the WhatsApp-first KL build.
"""
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.services.inbound import record_inbound_message
from app.workers.tasks import process_inbound_message

router = APIRouter(prefix="/api/v1/simulate", tags=["simulate"])


class SimulateInbound(BaseModel):
    phone_number_id: str = Field(description="tenant_channels.phone_number_id to route to")
    from_number: str = Field(description="Lead's number, e.g. +60123456789")
    body: str
    profile_name: str | None = None


@router.post("/inbound")
def simulate_inbound(req: SimulateInbound, db: Session = Depends(get_db)):
    if not get_settings().debug:
        raise HTTPException(status_code=404, detail="Not found")

    wa_id = req.from_number.lstrip("+")
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "SIMULATED",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": req.phone_number_id},
                            "contacts": [{"wa_id": wa_id, "profile": {"name": req.profile_name or "Sim User"}}],
                            "messages": [
                                {
                                    "from": wa_id,
                                    "id": f"wamid.SIM.{uuid.uuid4().hex}",
                                    "timestamp": str(int(time.time())),
                                    "type": "text",
                                    "text": {"body": req.body},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    new_message_ids = record_inbound_message(db, payload)
    for message_id in new_message_ids:
        process_inbound_message.delay(message_id)
    return {"simulated": True, "message_ids": new_message_ids}
