"""Health endpoints."""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - diagnostic surface
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": "unreachable", "error": str(exc)[:300]},
        )
    return {"status": "ok", "db": "connected"}
