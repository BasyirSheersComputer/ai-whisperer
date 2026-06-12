"""Serverless internal endpoints: cron auth + dispatch/reminders/init."""
from app.config import Settings


def test_internal_endpoints_work_in_debug(client, seeded_channel):
    assert client.get("/api/v1/internal/dispatch").json() == {"sent": 0}
    assert client.get("/api/v1/internal/reminders").json() == {"sent": 0}
    assert client.get("/api/v1/internal/init-db").json() == {"initialized": True}


def test_cron_secret_enforced(client, monkeypatch):
    import app.api.internal as mod

    locked = Settings(cron_secret="cr0n", debug=True)
    monkeypatch.setattr(mod, "get_settings", lambda: locked)
    assert client.get("/api/v1/internal/dispatch").status_code == 401
    assert client.get("/api/v1/internal/dispatch",
                      headers={"Authorization": "Bearer cr0n"}).status_code == 200


def test_cron_dispatch_actually_sends(client, seeded_channel, db_session):
    from datetime import datetime, timezone

    from app.models import ConsentBasis, Lead, LeadStatus
    from app.services.outbound import dispatch_due

    db_session.add(Lead(tenant_id=seeded_channel.tenant_id, phone_e164="+60125550001",
                        consent_basis=ConsentBasis.enquiry_form, status=LeadStatus.imported))
    db_session.commit()
    cid = client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns",
                      json={"name": "x"}).json()["id"]
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/enqueue")
    client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/campaigns/{cid}/start")

    # daytime MYT guaranteed via direct call with controlled now
    sent = dispatch_due(db_session, now=datetime(2026, 6, 15, 4, 0, tzinfo=timezone.utc))
    assert sent == 1
