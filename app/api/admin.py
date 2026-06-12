"""M6: agency admin APIs — onboarding, funnel, conversations, takeover, handoffs.

Auth: Bearer ADMIN_TOKEN (skipped when no token configured AND debug=true).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import (
    BusinessProfile,
    Conversation,
    ConversationState,
    Handoff,
    Lead,
    LeadStatus,
    Message,
    MessageDirection,
    Tenant,
    TenantChannel,
)
from app.services.whatsapp import WhatsAppClient

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def require_admin(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.admin_token:
        if settings.debug:
            return
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN not configured")
    if authorization != f"Bearer {settings.admin_token}":
        raise HTTPException(status_code=401, detail="Invalid admin token")


class OnboardTenant(BaseModel):
    name: str
    slug: str
    industry: str = "fitness"
    business_name: str
    core_offer: str | None = None
    booking_url: str | None = None
    faq_md: str | None = None
    pricing_md: str | None = None
    languages: list[str] = ["en", "ms"]
    phone_number_id: str | None = None
    display_number: str | None = None
    waba_id: str | None = None


@router.post("/tenants", dependencies=[Depends(require_admin)])
def onboard_tenant(body: OnboardTenant, db: Session = Depends(get_db)):
    """One-call tenant onboarding: tenant + channel + business profile."""
    if db.scalar(select(Tenant).where(Tenant.slug == body.slug)):
        raise HTTPException(status_code=409, detail=f"Slug {body.slug!r} already exists")
    tenant = Tenant(name=body.name, slug=body.slug, industry=body.industry, languages=body.languages)
    db.add(tenant)
    db.flush()
    db.add(TenantChannel(tenant_id=tenant.id, phone_number_id=body.phone_number_id,
                         display_number=body.display_number, waba_id=body.waba_id))
    db.add(BusinessProfile(tenant_id=tenant.id, business_name=body.business_name,
                           core_offer=body.core_offer, booking_url=body.booking_url,
                           faq_md=body.faq_md, pricing_md=body.pricing_md))
    db.commit()
    return {"tenant_id": tenant.id, "slug": tenant.slug}


@router.get("/tenants", dependencies=[Depends(require_admin)])
def list_tenants(db: Session = Depends(get_db)):
    tenants = db.scalars(select(Tenant).order_by(Tenant.created_at)).all()
    return [{"id": t.id, "name": t.name, "slug": t.slug, "industry": t.industry, "status": t.status} for t in tenants]


@router.get("/tenants/{tenant_id}/funnel", dependencies=[Depends(require_admin)])
def funnel(tenant_id: str, db: Session = Depends(get_db)):
    """The numbers clients buy on: sent -> replied -> qualified -> booked -> showed."""
    if db.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    counts = dict(
        db.execute(
            select(Lead.status, func.count(Lead.id)).where(Lead.tenant_id == tenant_id).group_by(Lead.status)
        ).all()
    )

    def n(*statuses: LeadStatus) -> int:
        return sum(int(counts.get(s, 0)) for s in statuses)

    total = sum(int(v) for v in counts.values())
    return {
        "total_leads": total,
        "contacted": n(LeadStatus.contacted, LeadStatus.engaged, LeadStatus.qualified,
                       LeadStatus.booked, LeadStatus.confirmed, LeadStatus.showed, LeadStatus.handed_off),
        "engaged": n(LeadStatus.engaged, LeadStatus.qualified, LeadStatus.booked,
                     LeadStatus.confirmed, LeadStatus.showed, LeadStatus.handed_off),
        "qualified": n(LeadStatus.qualified, LeadStatus.booked, LeadStatus.confirmed, LeadStatus.showed),
        "booked": n(LeadStatus.booked, LeadStatus.confirmed, LeadStatus.showed),
        "showed": n(LeadStatus.showed),
        "opted_out": n(LeadStatus.opted_out),
        "by_status": {k.value: int(v) for k, v in counts.items()},
    }


@router.get("/tenants/{tenant_id}/conversations", dependencies=[Depends(require_admin)])
def list_conversations(tenant_id: str, db: Session = Depends(get_db)):
    convos = db.scalars(
        select(Conversation).where(Conversation.tenant_id == tenant_id)
        .order_by(Conversation.last_message_at.desc()).limit(100)
    ).all()
    out = []
    for c in convos:
        lead = db.get(Lead, c.lead_id)
        out.append({
            "id": c.id, "lead_name": lead.name if lead else None,
            "lead_phone": lead.phone_e164 if lead else None,
            "state": c.state.value, "human": c.assigned_to_human,
            "last_message_at": str(c.last_message_at),
        })
    return out


@router.get("/conversations/{conversation_id}/messages", dependencies=[Depends(require_admin)])
def get_messages(conversation_id: str, db: Session = Depends(get_db)):
    msgs = db.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
    ).all()
    return [
        {"direction": m.direction.value, "body": m.body, "type": m.msg_type,
         "status": m.delivery_status, "at": str(m.created_at),
         "intent": (m.llm_meta or {}).get("intent")}
        for m in msgs
    ]


@router.post("/conversations/{conversation_id}/takeover", dependencies=[Depends(require_admin)])
def takeover(conversation_id: str, db: Session = Depends(get_db)):
    convo = db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    convo.assigned_to_human = True
    db.commit()
    return {"id": convo.id, "human": True}


@router.post("/conversations/{conversation_id}/release", dependencies=[Depends(require_admin)])
def release(conversation_id: str, db: Session = Depends(get_db)):
    """Hand the conversation back to the AI."""
    convo = db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    convo.assigned_to_human = False
    if convo.state == ConversationState.handed_off:
        convo.state = ConversationState.engaged
    db.commit()
    return {"id": convo.id, "human": False}


class ManualSend(BaseModel):
    body: str


@router.post("/conversations/{conversation_id}/send", dependencies=[Depends(require_admin)])
def manual_send(conversation_id: str, body: ManualSend, db: Session = Depends(get_db)):
    """Staff reply from the dashboard (requires takeover first)."""
    convo = db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not convo.assigned_to_human:
        raise HTTPException(status_code=409, detail="Take over the conversation before sending manually")
    lead = db.get(Lead, convo.lead_id)
    if lead.opted_out_at is not None:
        raise HTTPException(status_code=403, detail="Lead has opted out — sending is blocked (PDPA)")
    wamid = WhatsAppClient().send_text(lead.phone_e164, body.body)
    db.add(Message(conversation_id=convo.id, direction=MessageDirection.outbound,
                   body=body.body, wamid=wamid, msg_type="text",
                   llm_meta={"intent": "manual_staff_reply"}))
    convo.last_message_at = datetime.now(timezone.utc)
    db.commit()
    return {"sent": True, "wamid": wamid}


@router.get("/tenants/{tenant_id}/handoffs", dependencies=[Depends(require_admin)])
def handoff_inbox(tenant_id: str, db: Session = Depends(get_db)):
    rows = db.execute(
        select(Handoff, Conversation).join(Conversation, Conversation.id == Handoff.conversation_id)
        .where(Conversation.tenant_id == tenant_id, Handoff.resolved_at.is_(None))
        .order_by(Handoff.created_at.desc())
    ).all()
    out = []
    for h, c in rows:
        lead = db.get(Lead, c.lead_id)
        out.append({"id": h.id, "conversation_id": c.id, "reason": h.reason,
                    "lead_name": lead.name if lead else None, "at": str(h.created_at)})
    return out


@router.post("/handoffs/{handoff_id}/resolve", dependencies=[Depends(require_admin)])
def resolve_handoff(handoff_id: str, db: Session = Depends(get_db)):
    h = db.get(Handoff, handoff_id)
    if h is None:
        raise HTTPException(status_code=404, detail="Handoff not found")
    h.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": h.id, "resolved": True}
