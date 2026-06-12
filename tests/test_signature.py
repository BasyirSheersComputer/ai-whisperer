"""POST /webhooks/whatsapp — signature validation."""
import json

from tests.conftest import make_inbound_payload, sign


def test_invalid_signature_rejected(client, seeded_channel):
    body = json.dumps(make_inbound_payload()).encode()
    resp = client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=deadbeef", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_missing_signature_rejected(client, seeded_channel):
    body = json.dumps(make_inbound_payload()).encode()
    resp = client.post("/webhooks/whatsapp", content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 403


def test_valid_signature_accepted(client, seeded_channel):
    body = json.dumps(make_inbound_payload()).encode()
    resp = client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["received"] is True
