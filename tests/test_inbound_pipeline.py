"""End-to-end pipeline: webhook -> store -> reply (eager Celery, dry-run send + LLM)."""
import json

from sqlalchemy import select

from app.models import Conversation, Lead, Message, MessageDirection
from tests.conftest import make_inbound_payload, sign


def post_signed(client, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": sign(body), "Content-Type": "application/json"},
    )


def test_inbound_creates_lead_conversation_and_reply(client, seeded_channel, db_session):
    resp = post_signed(client, make_inbound_payload(body="Hi, still got promo ah?"))
    assert resp.status_code == 200
    assert resp.json()["queued"] == 1

    lead = db_session.scalar(select(Lead).where(Lead.phone_e164 == "+60123456789"))
    assert lead is not None
    assert lead.status.value == "engaged"
    assert lead.consent_basis.value == "inbound"

    convo = db_session.scalar(select(Conversation).where(Conversation.lead_id == lead.id))
    assert convo is not None
    assert convo.window_expires_at is not None

    msgs = db_session.scalars(select(Message).where(Message.conversation_id == convo.id)).all()
    inbound = [m for m in msgs if m.direction == MessageDirection.inbound]
    outbound = [m for m in msgs if m.direction == MessageDirection.outbound]
    assert len(inbound) == 1
    assert inbound[0].body == "Hi, still got promo ah?"
    assert len(outbound) == 1
    assert outbound[0].wamid.startswith("wamid.DRYRUN.")
    assert outbound[0].llm_meta["intent"] == "question"


def test_webhook_idempotent_on_meta_retry(client, seeded_channel, db_session):
    payload = make_inbound_payload(wamid="wamid.FIXED.1")
    assert post_signed(client, payload).json()["queued"] == 1
    assert post_signed(client, payload).json()["queued"] == 0  # retry dropped

    msgs = db_session.scalars(select(Message)).all()
    assert len([m for m in msgs if m.direction == MessageDirection.inbound]) == 1


def test_unknown_phone_number_id_dropped(client, seeded_channel, db_session):
    payload = make_inbound_payload(phone_number_id="UNKNOWN")
    resp = post_signed(client, payload)
    assert resp.status_code == 200
    assert resp.json()["queued"] == 0
    assert db_session.scalar(select(Lead)) is None


def test_delivery_status_updates_outbound_message(client, seeded_channel, db_session):
    post_signed(client, make_inbound_payload())
    out = db_session.scalar(select(Message).where(Message.direction == MessageDirection.outbound))
    status_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "E",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "PNID123"},
                            "statuses": [{"id": out.wamid, "status": "delivered"}],
                        },
                    }
                ],
            }
        ],
    }
    post_signed(client, status_payload)
    db_session.expire_all()
    assert db_session.get(Message, out.id).delivery_status == "delivered"


def test_opted_out_lead_gets_no_reply(client, seeded_channel, db_session):
    from datetime import datetime, timezone

    from app.models import ConsentBasis

    lead = Lead(
        tenant_id=seeded_channel.tenant_id,
        phone_e164="+60123456789",
        consent_basis=ConsentBasis.enquiry_form,
        opted_out_at=datetime.now(timezone.utc),
    )
    db_session.add(lead)
    db_session.commit()

    post_signed(client, make_inbound_payload())
    outbound = db_session.scalars(select(Message).where(Message.direction == MessageDirection.outbound)).all()
    assert outbound == []
