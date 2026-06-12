"""M4 outbound engine: throttled drip dispatch with compliance guards.

Every send re-checks suppression at send time; throttle = per-tenant hourly cap
+ per-tick batch + MYT quiet hours; quality circuit breaker pauses campaigns
when Meta downgrades the number.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AuditLog,
    Campaign,
    CampaignLead,
    ChannelType,
    Conversation,
    ConversationState,
    Lead,
    LeadStatus,
    Message,
    MessageDirection,
    Tenant,
    TenantChannel,
)
from app.services.whatsapp import WhatsAppClient

logger = logging.getLogger(__name__)

BAD_QUALITY = {"RED", "LOW", "FLAGGED", "DOWNGRADE", "RESTRICTED"}
MYT_OFFSET = 8  # Asia/Kuala_Lumpur, no DST


def _now() -> datetime:
    return datetime.now(timezone.utc)


def in_quiet_hours(tenant: Tenant, now: datetime) -> bool:
    qh = tenant.quiet_hours or {"start": get_settings().quiet_hours_start, "end": get_settings().quiet_hours_end}
    myt_hour = (now.hour + MYT_OFFSET) % 24
    start, end = int(qh.get("start", 21)), int(qh.get("end", 9))
    if start == end:
        return False
    if start < end:
        return start <= myt_hour < end
    return myt_hour >= start or myt_hour < end


def enqueue_eligible_leads(db: Session, campaign: Campaign) -> int:
    """Attach all eligible dormant leads to a campaign. Consent gate enforced at import,
    suppression re-checked here AND at send time."""
    already = set(db.scalars(select(CampaignLead.lead_id).where(CampaignLead.campaign_id == campaign.id)).all())
    leads = db.scalars(
        select(Lead).where(
            Lead.tenant_id == campaign.tenant_id,
            Lead.status.in_([LeadStatus.imported, LeadStatus.queued]),
            Lead.opted_out_at.is_(None),
        )
    ).all()
    n = 0
    for lead in leads:
        if lead.id in already:
            continue
        db.add(CampaignLead(campaign_id=campaign.id, lead_id=lead.id))
        lead.status = LeadStatus.queued
        n += 1
    db.commit()
    return n


def _sent_last_hour(db: Session, tenant_id: str, now: datetime) -> int:
    cutoff = now - timedelta(hours=1)
    return db.scalar(
        select(func.count(CampaignLead.id))
        .join(Campaign, Campaign.id == CampaignLead.campaign_id)
        .where(Campaign.tenant_id == tenant_id, CampaignLead.sent_at.isnot(None), CampaignLead.sent_at > cutoff)
    ) or 0


def pause_tenant_campaigns(db: Session, tenant_id: str, reason: str) -> int:
    campaigns = db.scalars(
        select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.status == "running")
    ).all()
    for c in campaigns:
        c.status = "paused_quality"
    if campaigns:
        db.add(AuditLog(tenant_id=tenant_id, actor="system", action="campaigns_paused",
                        entity="campaign", payload={"reason": reason, "count": len(campaigns)}))
    db.commit()
    return len(campaigns)


def dispatch_due(db: Session, now: datetime | None = None) -> int:
    """One scheduler tick: send due campaign messages within all limits. Returns sends."""
    now = now or _now()
    settings = get_settings()
    total_sent = 0

    campaigns = db.scalars(select(Campaign).where(Campaign.status == "running")).all()
    for campaign in campaigns:
        if campaign.start_at is not None and campaign.start_at > now:
            continue
        tenant = db.get(Tenant, campaign.tenant_id)
        if in_quiet_hours(tenant, now):
            continue

        channel = db.scalar(select(TenantChannel).where(
            TenantChannel.tenant_id == tenant.id, TenantChannel.type == ChannelType.whatsapp))
        if channel is None or channel.status != "active":
            continue
        if (channel.quality_rating or "").upper() in BAD_QUALITY:
            pause_tenant_campaigns(db, tenant.id, f"quality_rating={channel.quality_rating}")
            continue

        drip = campaign.drip_config or {}
        batch_size = int(drip.get("batch_size", 10))
        hourly_cap = int(drip.get("hourly_cap", settings.default_hourly_send_cap))
        budget = min(batch_size, hourly_cap - _sent_last_hour(db, tenant.id, now))
        if budget <= 0:
            continue

        due = db.scalars(
            select(CampaignLead)
            .where(CampaignLead.campaign_id == campaign.id, CampaignLead.status == "pending")
            .limit(budget)
        ).all()

        client = WhatsAppClient(phone_number_id=channel.phone_number_id)
        for cl in due:
            lead = db.get(Lead, cl.lead_id)
            # Send-time suppression re-check (PDPA/Meta).
            if lead is None or lead.opted_out_at is not None:
                cl.status = "suppressed"
                continue
            try:
                wamid = client.send_template(
                    lead.phone_e164,
                    campaign.template_name or "reactivation_generic",
                    campaign.template_lang or "en",
                )
            except Exception as exc:  # noqa: BLE001 - record per-lead failure, keep batch going
                cl.status = "error"
                cl.error = str(exc)[:500]
                logger.error("Send failed for lead %s: %s", lead.id, exc)
                continue

            convo = Conversation(
                tenant_id=tenant.id, lead_id=lead.id, channel_id=channel.id,
                state=ConversationState.contacted, last_message_at=now,
            )
            db.add(convo)
            db.flush()
            db.add(Message(
                conversation_id=convo.id, direction=MessageDirection.outbound,
                body=campaign.offer_text or f"[template:{campaign.template_name}]",
                wamid=wamid, template_name=campaign.template_name, msg_type="template",
            ))
            cl.status = "sent"
            cl.sent_at = now
            cl.wamid = wamid
            lead.status = LeadStatus.contacted
            lead.last_contact_date = now
            total_sent += 1

        db.flush()  # session has autoflush=False; flush status changes before counting
        pending_left = db.scalar(
            select(func.count(CampaignLead.id))
            .where(CampaignLead.campaign_id == campaign.id, CampaignLead.status == "pending")
        ) or 0
        if pending_left == 0:
            campaign.status = "completed"
        stats = dict(campaign.stats or {})
        stats["sent"] = int(stats.get("sent", 0)) + total_sent
        campaign.stats = stats

    db.commit()
    return total_sent


def send_due_booking_reminders(db: Session, now: datetime | None = None) -> int:
    """Send one T-24h reminder per booked appointment (cheap no-show insurance)."""
    from app.models import Booking, BookingStatus

    now = now or _now()
    due = db.scalars(
        select(Booking).where(
            Booking.status == BookingStatus.booked,
            Booking.reminder_sent_at.is_(None),
            Booking.slot_start > now + timedelta(hours=23),
            Booking.slot_start <= now + timedelta(hours=25),
        )
    ).all()
    sent = 0
    for booking in due:
        lead = db.get(Lead, booking.lead_id)
        if lead is None or lead.opted_out_at is not None:
            continue
        local = booking.slot_start.strftime("%a %d %b, %H:%M")
        client = WhatsAppClient()
        wamid = client.send_text(lead.phone_e164, f"Reminder: your appointment is tomorrow, {local} (MYT). Reply here if you need to reschedule!")
        if booking.conversation_id:
            db.add(Message(
                conversation_id=booking.conversation_id, direction=MessageDirection.outbound,
                body="[T-24h reminder]", wamid=wamid, msg_type="text",
            ))
        booking.reminder_sent_at = now
        sent += 1
    db.commit()
    return sent
