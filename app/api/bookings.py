"""M5: booking management (show/no-show tracking)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Booking, BookingStatus, Lead, LeadStatus, Tenant

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/bookings", tags=["bookings"])


@router.get("")
def list_bookings(tenant_id: str, db: Session = Depends(get_db)):
    if db.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    bookings = db.scalars(
        select(Booking).where(Booking.tenant_id == tenant_id).order_by(Booking.slot_start)
    ).all()
    out = []
    for b in bookings:
        lead = db.get(Lead, b.lead_id)
        out.append({
            "id": b.id, "lead_name": lead.name if lead else None,
            "lead_phone": lead.phone_e164 if lead else None,
            "slot_start": str(b.slot_start), "status": b.status.value,
            "reminded": b.reminder_sent_at is not None,
        })
    return out


class BookingPatch(BaseModel):
    status: str  # showed | no_show | cancelled | confirmed


@router.patch("/{booking_id}")
def update_booking(tenant_id: str, booking_id: str, body: BookingPatch, db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if booking is None or booking.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        new_status = BookingStatus(body.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid status {body.status!r}") from exc
    booking.status = new_status
    lead = db.get(Lead, booking.lead_id)
    if lead is not None and new_status == BookingStatus.showed:
        lead.status = LeadStatus.showed
    db.commit()
    return {"id": booking.id, "status": booking.status.value}
