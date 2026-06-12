"""Test fixtures: SQLite DB, eager Celery, dry-run WhatsApp, signed-webhook helper."""
import hashlib
import hmac
import os
import tempfile

import pytest

TEST_APP_SECRET = "test-app-secret"
TEST_VERIFY_TOKEN = "test-verify-token"

# Configure environment BEFORE importing the app.
_tmpdir = tempfile.mkdtemp()
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{_tmpdir}/test.db",
        "DEBUG": "true",
        "WHATSAPP_DRY_RUN": "true",
        "META_APP_SECRET": TEST_APP_SECRET,
        "META_VERIFY_TOKEN": TEST_VERIFY_TOKEN,
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.workers.celery_app import celery_app  # noqa: E402

celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    db = SessionLocal()
    yield db
    db.close()


def sign(body: bytes) -> str:
    digest = hmac.new(TEST_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def seeded_channel(db_session):
    """Create a tenant + channel and return the channel."""
    from app.models import BusinessProfile, Tenant, TenantChannel

    tenant = Tenant(name="Test Gym", slug="test-gym", industry="fitness")
    db_session.add(tenant)
    db_session.flush()
    channel = TenantChannel(tenant_id=tenant.id, phone_number_id="PNID123", display_number="+60311111111")
    db_session.add(channel)
    db_session.add(BusinessProfile(tenant_id=tenant.id, business_name="Test Gym"))
    db_session.commit()
    return channel


def make_inbound_payload(phone_number_id="PNID123", from_wa_id="60123456789", body="Hello", wamid=None):
    import uuid

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "ENTRY1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "60311111111", "phone_number_id": phone_number_id},
                            "contacts": [{"wa_id": from_wa_id, "profile": {"name": "Test Lead"}}],
                            "messages": [
                                {
                                    "from": from_wa_id,
                                    "id": wamid or f"wamid.TEST.{uuid.uuid4().hex}",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
