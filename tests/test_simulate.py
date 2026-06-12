"""Simulator endpoint (debug only)."""
from sqlalchemy import select

from app.models import Message, MessageDirection


def test_simulate_inbound_runs_full_pipeline(client, seeded_channel, db_session):
    resp = client.post(
        "/api/v1/simulate/inbound",
        json={
            "phone_number_id": "PNID123",
            "from_number": "+60198765432",
            "body": "Testing testing",
            "profile_name": "Sim Lead",
        },
    )
    assert resp.status_code == 200
    assert len(resp.json()["message_ids"]) == 1

    outbound = db_session.scalar(select(Message).where(Message.direction == MessageDirection.outbound))
    assert outbound is not None
    assert outbound.body == "Echo: Testing testing"
