"""FastAPI application entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from pathlib import Path

from fastapi.responses import HTMLResponse

from app.api import admin, bookings, campaigns, health, internal, leads, simulate, webhooks
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

_dsn = get_settings().sentry_dsn
if _dsn:  # pragma: no cover - optional dependency
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=_dsn, traces_sample_rate=0.1)
    except ImportError:
        logging.getLogger(__name__).warning("SENTRY_DSN set but sentry-sdk not installed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # create_all is a dev convenience (prod schema is migrated in Supabase).
    # Never let a DB hiccup at cold start take down the whole app — /healthz
    # reports DB state instead.
    from app.db import Base, engine

    try:
        Base.metadata.create_all(engine)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).error("Startup create_all failed (continuing): %s", exc)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(simulate.router)
    app.include_router(leads.router)
    app.include_router(campaigns.router)
    app.include_router(bookings.router)
    app.include_router(admin.router)
    app.include_router(internal.router)

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    def admin_page():
        page = Path(__file__).parent / "static" / "admin.html"
        return page.read_text(encoding="utf-8")
    return app


app = create_app()
