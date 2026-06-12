"""M2: state machine, multilingual opt-out, handoff, qualification."""
import json

import pytest
from sqlalchemy import select

from app.models import (
    AuditLog,
    Conversation,
    ConversationState,
    Handoff,
    Lead,
    LeadStatus,
    Message,
    MessageDirection,
)
from app.services import lexicon
from tests.conftest import make_inbound_payload, sign


def post_signed(client, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": sign(body), "Content-Type": "application/json"},
    )


# ---------- lexicon unit tests ----------

@pytest.mark.parametrize(
    "text",
    ["STOP", "stop.", "Berhenti", "tak nak lah", "Tolong jangan mesej saya", "不要再发", "please remove me", "unsubscribe"],
)
def test_opt_out_lexicon_matches(text):
    assert lexicon.is_opt_out(text)


@pytest.mark.parametrize("text", ["I want to stop by tomorrow", "non-stop gym sounds great", "ok boleh"])
def test_opt_out_lexicon_no_false_positive(text):
    assert not lexicon.is_opt_out(text)


@pytest.mark.parametrize("text", ["Can I talk to a human?", "nak cakap dengan orang", "请找真人"])
def test_human_request_lexicon(text):
    assert lexicon.is_human_request(text)


# ---------- opt-out flow ----------

@pytest.mark.parametrize("text", ["STOP", "tak nak", "不要再发"])
def test_opt_out_is_terminal_with_ack_and_audit(client, seeded_channel, db_session, text):
    post_signed(client, make_inbound_payload(body=text))

    lead = db_session.scalar(select(Lead))
    assert lead.opted_out_at is not None
    assert lead.status == LeadStatus.opted_out

    convo = db_session.scalar(select(Conversation))
    assert convo.state == ConversationState.opted_out

    outbound = db_session.scalars(select(Message).where(Message.direction == MessageDirection.outbound)).all()
    assert len(outbound) == 1  # single compliance ack
    assert "tidak akan" in outbound[0].body or "won't message" in outbound[0].body

    audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "opt_out"))
    assert audit is not None and audit.payload["lead_id"] == lead.id


def test_messages_after_opt_out_get_silence(client, seeded_channel, db_session):
    post_signed(client, make_inbound_payload(body="STOP", wamid="wamid.OPT.1"))
    post_signed(client, make_inbound_payload(body="actually wait", wamid="wamid.OPT.2"))

    outbound = db_session.scalars(select(Message).where(Message.direction == MessageDirection.outbound)).all()
    assert len(outbound) == 1  # only the original ack; no reply to the follow-up


# ---------- handoff flow ----------

def test_human_request_creates_handoff_and_pauses_ai(client, seeded_channel, db_session):
    post_signed(client, make_inbound_payload(body="Can I talk to a human?", wamid="wamid.H.1"))

    convo = db_session.scalar(select(Conversation))
    assert convo.state == ConversationState.handed_off
    assert convo.assigned_to_human is True
    assert db_session.scalar(select(Handoff)) is not None

    # Follow-up message: AI must stay silent while human owns the conversation.
    post_signed(client, make_inbound_payload(body="hello?", wamid="wamid.H.2"))
    outbound = db_session.scalars(select(Message).where(Message.direction == MessageDirection.outbound)).all()
    assert len(outbound) == 1  # only the handoff acknowledgment


# ---------- qualification & booking progression ----------

def test_positive_intent_qualifies_and_offers_booking(client, seeded_channel, db_session):
    post_signed(client, make_inbound_payload(body="ok can, interested"))

    lead = db_session.scalar(select(Lead))
    assert lead.status == LeadStatus.qualified

    convo = db_session.scalar(select(Conversation))
    assert convo.state == ConversationState.booking_offered

    outbound = db_session.scalar(select(Message).where(Message.direction == MessageDirection.outbound))
    assert "https://cal.com/test-gym/trial" in outbound.body
    assert outbound.llm_meta["intent"] == "positive"


def test_state_never_regresses(client, seeded_channel, db_session):
    post_signed(client, make_inbound_payload(body="ok can, interested", wamid="wamid.S.1"))
    convo = db_session.scalar(select(Conversation))
    assert convo.state == ConversationState.booking_offered

    # An 'unclear' follow-up must not drag the state back to engaged.
    post_signed(client, make_inbound_payload(body="hmmm", wamid="wamid.S.2"))
    db_session.expire_all()
    convo = db_session.scalar(select(Conversation))
    assert convo.state == ConversationState.booking_offered
