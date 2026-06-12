"""M4: campaign management endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Campaign, CampaignLead, Tenant
from app.services.outbound import enqueue_eligible_leads

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/campaigns", tags=["campaigns"])


def _tenant_or_404(db: Session, tenant_id: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def _campaign_or_404(db: Session, tenant_id: str, campaign_id: str) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


class CampaignIn(BaseModel):
    name: str
    template_name: str = "reactivation_generic"
    template_lang: str = "en"
    offer_text: str | None = None
    batch_size: int = 10
    hourly_cap: int = 50
    start_at: datetime | None = None


@router.post("")
def create_campaign(tenant_id: str, body: CampaignIn, db: Session = Depends(get_db)):
    _tenant_or_404(db, tenant_id)
    campaign = Campaign(
        tenant_id=tenant_id, name=body.name, template_name=body.template_name,
        template_lang=body.template_lang, offer_text=body.offer_text,
        drip_config={"batch_size": body.batch_size, "hourly_cap": body.hourly_cap},
        start_at=body.start_at, status="draft",
    )
    db.add(campaign)
    db.commit()
    return {"id": campaign.id, "status": campaign.status}


@router.post("/{campaign_id}/enqueue")
def enqueue(tenant_id: str, campaign_id: str, db: Session = Depends(get_db)):
    _tenant_or_404(db, tenant_id)
    campaign = _campaign_or_404(db, tenant_id, campaign_id)
    queued = enqueue_eligible_leads(db, campaign)
    return {"queued": queued}


@router.post("/{campaign_id}/start")
def start(tenant_id: str, campaign_id: str, db: Session = Depends(get_db)):
    _tenant_or_404(db, tenant_id)
    campaign = _campaign_or_404(db, tenant_id, campaign_id)
    campaign.status = "running"
    db.commit()
    return {"id": campaign.id, "status": "running"}


@router.post("/{campaign_id}/pause")
def pause(tenant_id: str, campaign_id: str, db: Session = Depends(get_db)):
    _tenant_or_404(db, tenant_id)
    campaign = _campaign_or_404(db, tenant_id, campaign_id)
    campaign.status = "paused"
    db.commit()
    return {"id": campaign.id, "status": "paused"}


@router.get("/{campaign_id}")
def get_campaign(tenant_id: str, campaign_id: str, db: Session = Depends(get_db)):
    _tenant_or_404(db, tenant_id)
    campaign = _campaign_or_404(db, tenant_id, campaign_id)
    counts = dict(
        db.execute(
            select(CampaignLead.status, func.count(CampaignLead.id))
            .where(CampaignLead.campaign_id == campaign_id)
            .group_by(CampaignLead.status)
        ).all()
    )
    return {"id": campaign.id, "name": campaign.name, "status": campaign.status,
            "drip_config": campaign.drip_config, "lead_counts": counts, "stats": campaign.stats}
