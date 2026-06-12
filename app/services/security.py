"""Webhook signature validation (Meta X-Hub-Signature-256)."""
import hashlib
import hmac

from app.config import get_settings


def verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Validate X-Hub-Signature-256 header against the app secret.

    Returns True when valid. If no app secret is configured AND debug is on,
    validation is skipped (local dev only).
    """
    settings = get_settings()
    if not settings.meta_app_secret:
        return settings.debug

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        settings.meta_app_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)
