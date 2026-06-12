"""M6: admin APIs — onboarding, funnel, takeover + manual send, handoff inbox, auth."""
import json

from app.config import Settings

from tests.conftest import make_inbound_payload, sign


def post_signed(client, payload):
    body = json.dumps(payload).encode()
    return client.post("/webhooks/whatsapp", content=body,
                       headers={"X-Hub-Signature-256": sign(body), "Content-Type": "application/json"})


def test_onboard_tenant_one_call(client):
    resp = client.post("/api/v1/admin/tenants", json={
        "name": "FitHub Bangsar", "slug": "fithub", "business_name": "FitHub Bangsar",
        "core_offer": "RM99 comeback", "booking_url": "https://cal.com/fithub/trial",
        "phone_number_id": "PNID999", "display_number": "+60322222222",
    })
    assert resp.status_code == 200
    tid = resp.json()["tenant_id"]
    assert client.post("/api/v1/admin/tenants", json={
        "name": "Dup", "slug": "fithub", "business_name": "Dup"}).status_code == 409
    tenants = client.get("/api/v1/admin/tenants").json()
    assert any(t["id"] == tid for t in tenants)


def test_funnel_math(client, seeded_channel, db_session):
    # one lead books, one opts out
    post_signed(client, make_inbound_payload(body="ok can", from_wa_id="60121111111", wamid="w.A1"))
    post_signed(client, make_inbound_payload(body="1", from_wa_id="60121111111", wamid="w.A2"))
    post_signed(client, make_inbound_payload(body="STOP", from_wa_id="60122222222", wamid="w.B1"))

    f = client.get(f"/api/v1/admin/tenants/{seeded_channel.tenant_id}/funnel").json()
    assert f["total_leads"] == 2
    assert f["booked"] == 1
    assert f["opted_out"] == 1


def test_takeover_silences_ai_and_manual_send(client, seeded_channel, db_session):
    from sqlalchemy import select

    from app.models import Conversation, Message, MessageDirection

    post_signed(client, make_inbound_payload(body="hello there", wamid="w.T1"))
    convo = db_session.scalar(select(Conversation))

    assert client.post(f"/api/v1/admin/conversations/{convo.id}/send",
                       json={"body": "hi"}).status_code == 409  # must take over first

    client.post(f"/api/v1/admin/conversations/{convo.id}/takeover")
    n_before = len(db_session.scalars(select(Message)).all())
    post_signed(client, make_inbound_payload(body="anyone home?", wamid="w.T2"))
    db_session.expire_all()
    msgs = db_session.scalars(select(Message)).all()
    assert len(msgs) == n_before + 1  # inbound stored, NO ai reply

    resp = client.post(f"/api/v1/admin/conversations/{convo.id}/send", json={"body": "Hi, Sarah here!"})
    assert resp.json()["sent"] is True
    db_session.expire_all()
    last = db_session.scalars(select(Message).where(Message.direction == MessageDirection.outbound)).all()[-1]
    assert last.body == "Hi, Sarah here!"
    assert last.llm_meta["intent"] == "manual_staff_reply"

    # release -> AI answers again
    client.post(f"/api/v1/admin/conversations/{convo.id}/release")
    post_signed(client, make_inbound_payload(body="got promo?", wamid="w.T3"))
    db_session.expire_all()
    newest = db_session.scalars(select(Message)).all()[-1]
    assert newest.direction == MessageDirection.outbound  # AI replied


def test_handoff_inbox_and_resolve(client, seeded_channel, db_session):
    post_signed(client, make_inbound_payload(body="can I talk to a human?", wamid="w.H1"))
    inbox = client.get(f"/api/v1/admin/tenants/{seeded_channel.tenant_id}/handoffs").json()
    assert len(inbox) == 1
    hid = inbox[0]["id"]
    assert client.post(f"/api/v1/admin/handoffs/{hid}/resolve").json()["resolved"] is True
    assert client.get(f"/api/v1/admin/tenants/{seeded_channel.tenant_id}/handoffs").json() == []


def test_admin_auth_enforced_when_token_set(client, monkeypatch):
    import app.api.admin as admin_mod

    locked = Settings(admin_token="sekret", debug=True)
    monkeypatch.setattr(admin_mod, "get_settings", lambda: locked)
    assert client.get("/api/v1/admin/tenants").status_code == 401
    assert client.get("/api/v1/admin/tenants",
                      headers={"Authorization": "Bearer sekret"}).status_code == 200


def test_admin_page_served(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Agency Admin" in resp.text
