"""Seed a demo tenant for local development.

Usage: python -m scripts.seed_demo
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import BusinessProfile, ConsentBasis, Lead, LeadStatus, Tenant, TenantChannel

DEMO_PHONE_NUMBER_ID = "1234567890"


def seed() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if db.scalar(select(Tenant).where(Tenant.slug == "demo-gym")):
            print("Demo tenant already seeded.")
            return

        tenant = Tenant(name="Demo Fitness KL", slug="demo-gym", industry="fitness")
        db.add(tenant)
        db.flush()

        db.add(
            TenantChannel(
                tenant_id=tenant.id,
                phone_number_id=DEMO_PHONE_NUMBER_ID,
                display_number="+60312345678",
                waba_id="DEMO_WABA",
            )
        )
        db.add(
            BusinessProfile(
                tenant_id=tenant.id,
                business_name="Demo Fitness KL",
                core_offer="RM99 first-month membership for returning members",
                booking_url="https://cal.com/demo-fitness-kl/trial",
                faq_md="**Hours:** 6am-11pm daily\n**Location:** Bangsar, KL\n**Parking:** Yes, free for members",
                hours={"daily": "06:00-23:00"},
            )
        )
        db.add(
            Lead(
                tenant_id=tenant.id,
                name="Aiman",
                phone_e164="+60123456789",
                source="seed",
                consent_basis=ConsentBasis.enquiry_form,
                consent_attested_by="seed-script",
                consent_date=datetime.now(timezone.utc),
                status=LeadStatus.imported,
            )
        )
        db.commit()
        print(f"Seeded tenant 'demo-gym' (phone_number_id={DEMO_PHONE_NUMBER_ID}).")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
