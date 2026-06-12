"""SQLAlchemy models — tenant-scoped schema per ARCHITECTURE_BUILD_PLAN.md §5.

Cross-database notes:
- JSON columns use sa.JSON (renders JSONB-compatible on Postgres, JSON on SQLite for tests).
- Enums use native_enum=False (VARCHAR + CHECK) for portability and painless migration.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


class ChannelType(str, enum.Enum):
    whatsapp = "whatsapp"
    sms = "sms"


class ConsentBasis(str, enum.Enum):
    existing_customer = "existing_customer"
    enquiry_form = "enquiry_form"
    walk_in = "walk_in"
    imported_attested = "imported_attested"
    inbound = "inbound"  # lead messaged us first


class LeadStatus(str, enum.Enum):
    imported = "imported"
    queued = "queued"
    contacted = "contacted"
    engaged = "engaged"
    qualified = "qualified"
    booked = "booked"
    confirmed = "confirmed"
    showed = "showed"
    opted_out = "opted_out"
    dead = "dead"
    handed_off = "handed_off"


class ConversationState(str, enum.Enum):
    queued = "queued"
    contacted = "contacted"
    engaged = "engaged"
    qualified = "qualified"
    booking_offered = "booking_offered"
    booked = "booked"
    confirmed = "confirmed"
    opted_out = "opted_out"
    handed_off = "handed_off"
    stale = "stale"
    dead = "dead"


class MessageDirection(str, enum.Enum):
    inbound = "in"
    outbound = "out"


class BookingStatus(str, enum.Enum):
    offered = "offered"
    booked = "booked"
    confirmed = "confirmed"
    showed = "showed"
    no_show = "no_show"
    cancelled = "cancelled"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    industry: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="active")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kuala_Lumpur")
    languages: Mapped[list | None] = mapped_column(JSON, default=lambda: ["en", "ms"])
    quiet_hours: Mapped[dict | None] = mapped_column(JSON, default=lambda: {"start": 21, "end": 9})
    dpo_contact: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    channels: Mapped[list["TenantChannel"]] = relationship(back_populates="tenant")
    profile: Mapped["BusinessProfile | None"] = relationship(back_populates="tenant", uselist=False)


class TenantChannel(Base):
    __tablename__ = "tenant_channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    type: Mapped[ChannelType] = mapped_column(Enum(ChannelType, native_enum=False), default=ChannelType.whatsapp)
    waba_id: Mapped[str | None] = mapped_column(String(64))
    phone_number_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    display_number: Mapped[str | None] = mapped_column(String(32))
    access_token_enc: Mapped[str | None] = mapped_column(Text)  # encrypted at rest
    quality_rating: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default="active")

    tenant: Mapped["Tenant"] = relationship(back_populates="channels")


class BusinessProfile(Base):
    __tablename__ = "business_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, unique=True)
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    core_offer: Mapped[str | None] = mapped_column(Text)
    booking_url: Mapped[str | None] = mapped_column(String(512))
    faq_md: Mapped[str | None] = mapped_column(Text)
    pricing_md: Mapped[str | None] = mapped_column(Text)
    hours: Mapped[dict | None] = mapped_column(JSON)
    current_promos: Mapped[dict | None] = mapped_column(JSON)

    tenant: Mapped["Tenant"] = relationship(back_populates="profile")


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("tenant_id", "phone_e164", name="uq_lead_tenant_phone"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    language_pref: Mapped[str | None] = mapped_column(String(8))
    source: Mapped[str | None] = mapped_column(String(64))
    consent_basis: Mapped[ConsentBasis] = mapped_column(Enum(ConsentBasis, native_enum=False), nullable=False)
    consent_attested_by: Mapped[str | None] = mapped_column(String(255))
    consent_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_contact_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, native_enum=False), default=LeadStatus.imported, index=True
    )
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_name: Mapped[str | None] = mapped_column(String(255))
    template_lang: Mapped[str] = mapped_column(String(8), default="en")
    offer_text: Mapped[str | None] = mapped_column(Text)
    drip_config: Mapped[dict | None] = mapped_column(JSON)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    stats: Mapped[dict | None] = mapped_column(JSON)


class CampaignLead(Base):
    __tablename__ = "campaign_leads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), nullable=False, index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wamid: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error: Mapped[str | None] = mapped_column(Text)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), nullable=False, index=True)
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_channels.id"))
    state: Mapped[ConversationState] = mapped_column(
        Enum(ConversationState, native_enum=False), default=ConversationState.contacted
    )
    window_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_to_human: Mapped[bool] = mapped_column(Boolean, default=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), nullable=False, index=True)
    direction: Mapped[MessageDirection] = mapped_column(Enum(MessageDirection, native_enum=False), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    wamid: Mapped[str | None] = mapped_column(String(128), index=True)
    template_name: Mapped[str | None] = mapped_column(String(255))
    msg_type: Mapped[str] = mapped_column(String(32), default="text")
    llm_meta: Mapped[dict | None] = mapped_column(JSON)
    delivery_status: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"))
    calendar_provider: Mapped[str | None] = mapped_column(String(32))
    external_event_id: Mapped[str | None] = mapped_column(String(128))
    slot_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    slot_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus, native_enum=False), default=BookingStatus.offered)


class Handoff(Base):
    __tablename__ = "handoffs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    alerted_via: Mapped[str | None] = mapped_column(String(32))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
