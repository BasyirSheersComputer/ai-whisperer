"""M3: CSV import with consent gate, phone normalisation, webhook lead, PDPA DSR."""
import io
import json

from sqlalchemy import select

from app.models import AuditLog, Lead, Message
from app.services.phone import normalize_msisdn
from tests.conftest import make_inbound_payload, sign


def test_phone_normalisation():
    assert normalize_msisdn("012-345 6789") == "+60123456789"
    assert normalize_msisdn("60123456789") == "+60123456789"
    assert normalize_msisdn("+60 12 345 6789") == "+60123456789"
    assert normalize_msisdn("0060123456789") == "+60123456789"
    assert normalize_msisdn("+6598765432") == "+6598765432"  # SG kept as-is
    assert normalize_msisdn("abc") is None
    assert normalize_msisdn("") is None
    assert normalize_msisdn("123") is None


CSV = """Name,Phone Number,Notes
Aiman,012-345 6789,trial signup
Duplicate Aiman,0123456789,same person
Mei Ling,+60198765432,expired member
Junk Row,not-a-phone,???
Opted Out Guy,011-2222 3333,old optout
"""


def _import(client, tenant_id, csv_text, basis="enquiry_form", attested_by="Owner Tan"):
    return client.post(
        f"/api/v1/tenants/{tenant_id}/leads/import-csv",
        files={"file": ("leads.csv", io.BytesIO(csv_text.encode()), "text/csv")},
        data={"consent_basis": basis, "attested_by": attested_by},
    )


def test_csv_import_with_consent_gate(client, seeded_channel, db_session):
    from datetime import datetime, timezone

    from app.models import ConsentBasis

    # Pre-existing opted-out lead must be suppressed on re-import.
    db_session.add(Lead(tenant_id=seeded_channel.tenant_id, phone_e164="+601122223333",
                        consent_basis=ConsentBasis.walk_in, opted_out_at=datetime.now(timezone.utc)))
    db_session.commit()

    resp = _import(client, seeded_channel.tenant_id, CSV)
    assert resp.status_code == 200
    assert resp.json() == {"imported": 2, "duplicate": 1, "invalid": 1, "suppressed": 1}

    lead = db_session.scalar(select(Lead).where(Lead.phone_e164 == "+60123456789"))
    assert lead.name == "Aiman"
    assert lead.consent_basis.value == "enquiry_form"
    assert lead.consent_attested_by == "Owner Tan"

    audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "consent_attestation"))
    assert audit.payload["imported"] == 2


def test_csv_import_rejects_bad_consent_basis(client, seeded_channel):
    resp = _import(client, seeded_channel.tenant_id, CSV, basis="inbound")
    assert resp.status_code == 400
    resp = _import(client, seeded_channel.tenant_id, CSV, basis="bought_list")
    assert resp.status_code == 400


def test_csv_import_unknown_tenant_404(client, seeded_channel):
    assert _import(client, "nope", CSV).status_code == 404


def test_webhook_lead_create_and_dedupe(client, seeded_channel, db_session):
    body = {"name": "Zara", "phone": "013 999 8877", "consent_basis": "existing_customer", "attested_by": "Owner Tan"}
    r1 = client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/leads", json=body)
    assert r1.status_code == 200 and r1.json()["result"] == "imported"
    r2 = client.post(f"/api/v1/tenants/{seeded_channel.tenant_id}/leads", json=body)
    assert r2.json()["result"] == "duplicate"
    assert r1.json()["phone"] == "+60139998877"


def test_dsr_export_and_delete(client, seeded_channel, db_session):
    # Lead messages in -> has conversation + messages.
    payload = make_inbound_payload(body="Hi there")
    raw = json.dumps(payload).encode()
    client.post("/webhooks/whatsapp", content=raw,
                headers={"X-Hub-Signature-256": sign(raw), "Content-Type": "application/json"})

    lead = db_session.scalar(select(Lead))
    resp = client.get(f"/api/v1/tenants/{seeded_channel.tenant_id}/leads/{lead.id}/export")
    assert resp.status_code == 200
    data = resp.json()
    assert data["lead"]["phone"] == "+60123456789"
    assert len(data["messages"]) >= 2  # inbound + reply

    resp = client.delete(f"/api/v1/tenants/{seeded_channel.tenant_id}/leads/{lead.id}")
    assert resp.json()["deleted"] is True
    db_session.expire_all()
    assert db_session.scalar(select(Lead)) is None
    assert db_session.scalars(select(Message)).all() == []
    assert db_session.scalar(select(AuditLog).where(AuditLog.action == "dsr_delete")) is not None
