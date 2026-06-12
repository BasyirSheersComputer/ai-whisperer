"""Cron-triggered internal endpoints for serverless deployments (Vercel).

On Vercel there is no Celery beat; vercel.json crons hit these endpoints instead.
Auth: Authorization: Bearer <CRON_SECRET> (Vercel sends this automatically when
the CRON_SECRET env var is set). Allowed without a secret only in debug mode.
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db

router = APIRouter(prefix="/api/v1/internal", tags=["internal"])


def require_cron(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.cron_secret:
        if settings.debug:
            return
        raise HTTPException(status_code=503, detail="CRON_SECRET not configured")
    if authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Invalid cron secret")


@router.get("/dispatch", dependencies=[Depends(require_cron)])
def cron_dispatch(db: Session = Depends(get_db)):
    """Campaign drip tick (Celery-beat equivalent for serverless)."""
    from app.services.outbound import dispatch_due

    return {"sent": dispatch_due(db)}


@router.get("/reminders", dependencies=[Depends(require_cron)])
def cron_reminders(db: Session = Depends(get_db)):
    """T-24h booking reminder tick."""
    from app.services.outbound import send_due_booking_reminders

    return {"sent": send_due_booking_reminders(db)}


@router.get("/init-db", dependencies=[Depends(require_cron)])
def init_db():
    """One-time schema creation (serverless cold starts may skip lifespan)."""
    from app.db import Base, engine

    Base.metadata.create_all(engine)
    return {"initialized": True}
