"""M4: campaign enqueue, throttled dispatch, quiet hours, quality circuit breaker."""
import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Campaign, CampaignLead, ConsentBasis, Conversation, Lead, LeadStatus, Message
from app.services.outbound import dispatch_due, in_quiet_hours
from tests.conftest import make_inbound_payload, sign  # noqa: F401

# 04:00 UTC = 12:00 MYT — safely outside default quiet hours (21:00-09:00 MYT)
DAYTIME = datetime(2026, 6, 15, 4, 0, tzinfo=timezone.utc)
# 16:00 UTC = 00:00 MYT — inside quiet hours
MIDNIGHT_MYT = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)


def _seed_leads(db, tenant_id, n=5, opted_out_idx=None):
    leads = []
    for i in range(n):
        lead = Lead(
            tenant_id=tenant_id, name=f"Lead{i}", phone_e164=f"+6012000000{i}",
            consent_basis=ConsentBasis.enquiry_form, consent_attested_by="owner",
            status=LeadStatus.imported,
            opted_out_at=datetime.now(timezone.utc) if i == opted_out_idx else None,
        )
        db.add(lead)
        leads.append(lead)
    db.commit()
    return leads


def _make_campaign(client, tenant_id, batch_size=10, hourly_cap=50):
    resp = client.post(
        f"/api/v1/tenants/{tenant_id}/campaigns",
        json={"name": "Comeback June", "offer_text": "RM99 comeback offer!",
              "batch_size": batch_size, "hourly_cap": hourly_cap},
    )
    return resp.json()["id"]


def test_enqueue_skips_opted_out(client, seeded_channel, db_session):
    _seed_leads(db_session, seeded_channel.tenant_id, n=5, opted_out_idx=2)
    cid = _make_campaign(client, seeded_channel.tenant_id)
    resp = client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/enqueue")
    assert resp.json()["queued"] == 4  # opted-out lead excluded


def test_dispatch_respects_batch_and_creates_conversations(client, seeded_channel, db_session):
    _seed_leads(db_session, seeded_channel.tenant_id, n=5)
    cid = _make_campaign(client, seeded_channel.tenant_id, batch_size=2)
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/enqueue")
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/start")

    sent = dispatch_due(db_session, now=DAYTIME)
    assert sent == 2  # batch_size cap per tick

    convos = db_session.scalars(select(Conversation)).all()
    assert len(convos) == 2
    assert all(c.state.value == "contacted" for c in convos)
    msgs = db_session.scalars(select(Message)).all()
    assert all(m.msg_type == "template" for m in msgs)
    contacted = db_session.scalars(select(Lead).where(Lead.status == LeadStatus.contacted)).all()
    assert len(contacted) == 2


def test_dispatch_respects_hourly_cap(client, seeded_channel, db_session):
    _seed_leads(db_session, seeded_channel.tenant_id, n=5)
    cid = _make_campaign(client, seeded_channel.tenant_id, batch_size=10, hourly_cap=3)
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/enqueue")
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/start")

    assert dispatch_due(db_session, now=DAYTIME) == 3   # cap reached
    assert dispatch_due(db_session, now=DAYTIME) == 0   # same hour: nothing more


def test_dispatch_silent_during_quiet_hours(client, seeded_channel, db_session):
    _seed_leads(db_session, seeded_channel.tenant_id, n=3)
    cid = _make_campaign(client, seeded_channel.tenant_id)
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/enqueue")
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/start")

    assert dispatch_due(db_session, now=MIDNIGHT_MYT) == 0
    assert dispatch_due(db_session, now=DAYTIME) == 3


def test_send_time_suppression_recheck(client, seeded_channel, db_session):
    leads = _seed_leads(db_session, seeded_channel.tenant_id, n=2)
    cid = _make_campaign(client, seeded_channel.tenant_id)
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/enqueue")
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/start")

    # Lead opts out AFTER being enqueued but BEFORE dispatch.
    leads[0].opted_out_at = datetime.now(timezone.utc)
    db_session.commit()

    assert dispatch_due(db_session, now=DAYTIME) == 1
    cl = db_session.scalar(select(CampaignLead).where(CampaignLead.lead_id == leads[0].id))
    assert cl.status == "suppressed"


def test_quality_webhook_pauses_campaigns(client, seeded_channel, db_session):
    _seed_leads(db_session, seeded_channel.tenant_id, n=2)
    cid = _make_campaign(client, seeded_channel.tenant_id)
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/enqueue")
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/start")

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "E", "changes": [{
            "field": "phone_number_quality_update",
            "value": {"display_phone_number": "+60311111111", "event": "FLAGGED"},
        }]}],
    }
    raw = json.dumps(payload).encode()
    client.post("/webhooks/whatsapp", content=raw,
                headers={"X-Hub-Signature-256": sign(raw), "Content-Type": "application/json"})

    db_session.expire_all()
    campaign = db_session.get(Campaign, cid)
    assert campaign.status == "paused_quality"
    assert dispatch_due(db_session, now=DAYTIME) == 0


def test_campaign_completes_when_drained(client, seeded_channel, db_session):
    _seed_leads(db_session, seeded_channel.tenant_id, n=2)
    cid = _make_campaign(client, seeded_channel.tenant_id, batch_size=10)
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/enqueue")
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/start")

    dispatch_due(db_session, now=DAYTIME)
    db_session.expire_all()
    assert db_session.get(Campaign, cid).status == "completed"

    stats = client.get(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}").json()
    assert stats["lead_counts"].get("sent") == 2


def test_quiet_hours_logic(seeded_channel, db_session):
    from app.models import Tenant
    tenant = db_session.get(Tenant, seeded_channel.tenant_id)
    assert in_quiet_hours(tenant, MIDNIGHT_MYT) is True
    assert in_quiet_hours(tenant, DAYTIME) is False
