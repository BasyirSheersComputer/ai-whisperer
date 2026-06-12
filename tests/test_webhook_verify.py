"""GET /webhooks/whatsapp — Meta subscription verification."""
from tests.conftest import TEST_VERIFY_TOKEN


def test_verify_success(client):
    resp = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": TEST_VERIFY_TOKEN, "hub.challenge": "12345"},
    )
    assert resp.status_code == 200
    assert resp.text == "12345"


def test_verify_wrong_token(client):
    resp = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345"},
    )
    assert resp.status_code == 403


def test_verify_missing_params(client):
    resp = client.get("/webhooks/whatsapp")
    assert resp.status_code == 403


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok", "db": "connected"}
