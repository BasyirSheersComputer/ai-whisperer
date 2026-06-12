"""Lead ingestion (M3): CSV import with consent gate, single-lead webhook, PDPA DSR."""
import csv
import io
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    AuditLog,
    Booking,
    CampaignLead,
    ConsentBasis,
    Conversation,
    Lead,
    LeadStatus,
    Message,
    Tenant,
)
from app.services.phone import normalize_msisdn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/leads", tags=["leads"])

# 'inbound' is reserved for leads who message us first; imports must attest a real basis.
IMPORTABLE_BASES = {b.value for b in ConsentBasis} - {ConsentBasis.inbound.value}

NAME_COLUMNS = {"name", "full name", "fullname", "nama", "first name", "customer name"}
PHONE_COLUMNS = {"phone", "phone number", "phonenumber", "mobile", "mobile number", "no tel", "no telefon", "telefon", "whatsapp", "hp", "contact", "contact number"}


def _get_tenant(db: Session, tenant_id: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def _consent_or_400(consent_basis: str) -> ConsentBasis:
    if consent_basis not in IMPORTABLE_BASES:
        raise HTTPException(
            status_code=400,
            detail=f"consent_basis must be one of {sorted(IMPORTABLE_BASES)} — "
            "leads may only be imported with an attested prior-consent basis (PDPA).",
        )
    return ConsentBasis(consent_basis)


def _upsert_lead(db: Session, tenant_id: str, name: str | None, phone: str,
                 basis: ConsentBasis, attested_by: str, source: str | None) -> str:
    """Returns one of: imported | duplicate | suppressed."""
    existing = db.scalar(select(Lead).where(Lead.tenant_id == tenant_id, Lead.phone_e164 == phone))
    if existing is not None:
        if existing.opted_out_at is not None:
            return "suppressed"
        return "duplicate"
    db.add(
        Lead(
            tenant_id=tenant_id,
            name=(name or "").strip() or None,
            phone_e164=phone,
            source=source,
            consent_basis=basis,
            consent_attested_by=attested_by,
            consent_date=datetime.now(timezone.utc),
            status=LeadStatus.imported,
        )
    )
    return "imported"


@router.post("/import-csv")
async def import_csv(
    tenant_id: str,
    file: UploadFile = File(...),
    consent_basis: str = Form(...),
    attested_by: str = Form(...),
    source: str = Form(default="csv_import"),
    db: Session = Depends(get_db),
):
    _get_tenant(db, tenant_id)
    basis = _consent_or_400(consent_basis)

    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="Empty or unreadable CSV")

    field_map = {f.lower().strip(): f for f in reader.fieldnames}
    name_col = next((field_map[c] for c in NAME_COLUMNS if c in field_map), None)
    phone_col = next((field_map[c] for c in PHONE_COLUMNS if c in field_map), None)
    if phone_col is None:
        raise HTTPException(status_code=400, detail=f"No phone column found. Columns: {reader.fieldnames}")

    counts = {"imported": 0, "duplicate": 0, "invalid": 0, "suppressed": 0}
    seen: set[str] = set()
    for row in reader:
        phone = normalize_msisdn(row.get(phone_col))
        if phone is None:
            counts["invalid"] += 1
            continue
        if phone in seen:
            counts["duplicate"] += 1
            continue
        seen.add(phone)
        result = _upsert_lead(db, tenant_id, row.get(name_col) if name_col else None,
                              phone, basis, attested_by, source)
        counts[result] += 1

    db.add(AuditLog(
        tenant_id=tenant_id, actor=attested_by, action="consent_attestation", entity="lead_import",
        payload={"consent_basis": basis.value, "file": file.filename, **counts},
    ))
    db.commit()
    return counts


class LeadIn(BaseModel):
    name: str | None = None
    phone: str
    consent_basis: str
    attested_by: str
    source: str | None = "webhook"


@router.post("")
def create_lead(tenant_id: str, body: LeadIn, db: Session = Depends(get_db)):
    """Single-lead ingestion — Zapier/Make-friendly JSON webhook."""
    _get_tenant(db, tenant_id)
    basis = _consent_or_400(body.consent_basis)
    phone = normalize_msisdn(body.phone)
    if phone is None:
        raise HTTPException(status_code=400, detail=f"Unusable phone number: {body.phone!r}")
    result = _upsert_lead(db, tenant_id, body.name, phone, basis, body.attested_by, body.source)
    db.add(AuditLog(
        tenant_id=tenant_id, actor=body.attested_by, action="consent_attestation", entity="lead_webhook",
        payload={"consent_basis": basis.value, "phone": phone, "result": result},
    ))
    db.commit()
    return {"result": result, "phone": phone}


@router.get("")
def list_leads(tenant_id: str, status: str | None = None, db: Session = Depends(get_db)):
    _get_tenant(db, tenant_id)
    q = select(Lead).where(Lead.tenant_id == tenant_id)
    if status:
        q = q.where(Lead.status == LeadStatus(status))
    leads = db.scalars(q.order_by(Lead.created_at.desc()).limit(500)).all()
    return [
        {"id": l.id, "name": l.name, "phone": l.phone_e164, "status": l.status.value,
         "consent_basis": l.consent_basis.value, "opted_out": l.opted_out_at is not None}
        for l in leads
    ]


# ---------- PDPA data subject rights ----------

@router.get("/{lead_id}/export")
def export_lead(tenant_id: str, lead_id: str, db: Session = Depends(get_db)):
    """PDPA access/portability: full export of one lead's data."""
    _get_tenant(db, tenant_id)
    lead = db.get(Lead, lead_id)
    if lead is None or lead.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Lead not found")
    convos = db.scalars(select(Conversation).where(Conversation.lead_id == lead_id)).all()
    convo_ids = [c.id for c in convos]
    msgs = db.scalars(select(Message).where(Message.conversation_id.in_(convo_ids)).order_by(Message.created_at)).all() if convo_ids else []
    db.add(AuditLog(tenant_id=tenant_id, actor="api", action="dsr_export", entity="lead", payload={"lead_id": lead_id}))
    db.commit()
    return {
        "lead": {"id": lead.id, "name": lead.name, "phone": lead.phone_e164,
                 "consent_basis": lead.consent_basis.value, "consent_date": str(lead.consent_date),
                 "status": lead.status.value},
        "messages": [{"direction": m.direction.value, "body": m.body, "at": str(m.created_at)} for m in msgs],
    }


@router.delete("/{lead_id}")
def delete_lead(tenant_id: str, lead_id: str, db: Session = Depends(get_db)):
    """PDPA erasure: hard-delete the lead and every trace of their conversations."""
    _get_tenant(db, tenant_id)
    lead = db.get(Lead, lead_id)
    if lead is None or lead.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Lead not found")
    convo_ids = db.scalars(select(Conversation.id).where(Conversation.lead_id == lead_id)).all()
    if convo_ids:
        db.execute(sa_delete(Message).where(Message.conversation_id.in_(convo_ids)))
        db.execute(sa_delete(Conversation).where(Conversation.id.in_(convo_ids)))
    db.execute(sa_delete(Booking).where(Booking.lead_id == lead_id))
    db.execute(sa_delete(CampaignLead).where(CampaignLead.lead_id == lead_id))
    db.delete(lead)
    db.add(AuditLog(tenant_id=tenant_id, actor="api", action="dsr_delete", entity="lead",
                    payload={"lead_id": lead_id, "phone": lead.phone_e164}))
    db.commit()
    return {"deleted": True}
