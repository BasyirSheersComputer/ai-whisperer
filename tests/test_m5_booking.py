"""M5: slot offer, in-chat booking, reminders, no-show tracking."""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Booking, BookingStatus, Conversation, ConversationState, Lead, LeadStatus, Message, MessageDirection
from app.services.outbound import send_due_booking_reminders
from tests.conftest import make_inbound_payload, sign


def post_signed(client, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": sign(body), "Content-Type": "application/json"},
    )


def _say(client, text, wamid):
    post_signed(client, make_inbound_payload(body=text, wamid=wamid))


def test_positive_offers_numbered_slots(client, seeded_channel, db_session):
    _say(client, "ok can, interested", "wamid.B.1")
    offer = db_session.scalar(select(Message).where(Message.direction == MessageDirection.outbound))
    assert "reply 1, 2 or 3" in offer.body
    assert "1)" in offer.body and "3)" in offer.body
    assert "https://cal.com/test-gym/trial" in offer.body
    assert len(offer.llm_meta["offered_slots"]) == 3


def test_slot_selection_books_and_confirms(client, seeded_channel, db_session):
    _say(client, "ok can", "wamid.B.2")
    _say(client, "2", "wamid.B.3")

    booking = db_session.scalar(select(Booking))
    assert booking is not None
    assert booking.status == BookingStatus.booked
    assert booking.external_event_id.startswith("calcom.DRYRUN.")

    db_session.expire_all()
    convo = db_session.scalar(select(Conversation))
    assert convo.state == ConversationState.booked
    lead = db_session.scalar(select(Lead))
    assert lead.status == LeadStatus.booked

    confirmation = db_session.scalars(
        select(Message).where(Message.direction == MessageDirection.outbound).order_by(Message.created_at)
    ).all()[-1]
    assert "Locked in!" in confirmation.body


def test_non_slot_reply_after_offer_falls_through_to_llm(client, seeded_channel, db_session):
    _say(client, "ok can", "wamid.B.4")
    _say(client, "what should I bring ah?", "wamid.B.5")

    assert db_session.scalar(select(Booking)) is None
    db_session.expire_all()
    convo = db_session.scalar(select(Conversation))
    assert convo.state == ConversationState.booking_offered  # no regression


def test_reminder_sent_once_in_t24_window(client, seeded_channel, db_session):
    _say(client, "ok can", "wamid.B.6")
    _say(client, "1", "wamid.B.7")
    booking = db_session.scalar(select(Booking))

    now = datetime.now(timezone.utc)
    # Outside window: nothing.
    booking.slot_start = now + timedelta(hours=48)
    db_session.commit()
    assert send_due_booking_reminders(db_session, now=now) == 0

    # Inside T-24h window: one reminder, exactly once.
    booking.slot_start = now + timedelta(hours=24)
    db_session.commit()
    assert send_due_booking_reminders(db_session, now=now) == 1
    assert send_due_booking_reminders(db_session, now=now) == 0
    db_session.expire_all()
    assert db_session.scalar(select(Booking)).reminder_sent_at is not None


def test_no_show_tracking_endpoint(client, seeded_channel, db_session):
    _say(client, "ok can", "wamid.B.8")
    _say(client, "3", "wamid.B.9")
    booking = db_session.scalar(select(Booking))

    resp = client.patch(
        f"/api/v1/tenants/{seeded_channel.tenant_id}/bookings/{booking.id}",
        json={"status": "showed"},
    )
    assert resp.json()["status"] == "showed"
    db_session.expire_all()
    assert db_session.scalar(select(Lead)).status == LeadStatus.showed

    listing = client.get(f"/api/v1/tenants/{seeded_channel.tenant_id}/bookings").json()
    assert len(listing) == 1 and listing[0]["status"] == "showed"
