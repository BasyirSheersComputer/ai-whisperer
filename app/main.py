"""FastAPI application entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, simulate, webhooks
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # M1: create_all keeps dev/test bootstrap simple; Alembic migrations land in M3
    # when the schema first changes against live data.
    from app.db import Base, engine

    Base.metadata.create_all(engine)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(simulate.router)
    return app


app = create_app()
