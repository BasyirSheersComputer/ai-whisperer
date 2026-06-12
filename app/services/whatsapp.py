"""Meta WhatsApp Cloud API client.

Dry-run mode (default in dev/test) logs and returns a fake wamid instead of
calling Meta, so the full pipeline is exercisable without a WABA.
"""
import logging
import uuid

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class WhatsAppSendError(Exception):
    pass


class WhatsAppClient:
    def __init__(self, phone_number_id: str | None = None, access_token: str | None = None):
        settings = get_settings()
        self.base = settings.graph_api_base
        self.phone_number_id = phone_number_id or settings.meta_phone_number_id
        self.access_token = access_token or settings.meta_access_token
        self.dry_run = settings.whatsapp_dry_run

    def _post(self, payload: dict) -> str:
        """Send payload to Meta; return the wamid."""
        if self.dry_run:
            fake_wamid = f"wamid.DRYRUN.{uuid.uuid4().hex}"
            logger.info("[DRY RUN] WhatsApp send to %s: %s", payload.get("to"), payload)
            return fake_wamid

        url = f"{self.base}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            logger.error("WhatsApp send failed (%s): %s", resp.status_code, resp.text)
            raise WhatsAppSendError(f"{resp.status_code}: {resp.text}")
        data = resp.json()
        try:
            return data["messages"][0]["id"]
        except (KeyError, IndexError) as exc:
            raise WhatsAppSendError(f"Unexpected response: {data}") from exc

    def send_text(self, to_e164: str, body: str) -> str:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_e164.lstrip("+"),
            "type": "text",
            "text": {"preview_url": True, "body": body},
        }
        return self._post(payload)

    def send_template(self, to_e164: str, template_name: str, lang_code: str = "en", components: list | None = None) -> str:
        payload = {
            "messaging_product": "whatsapp",
            "to": to_e164.lstrip("+"),
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": lang_code},
                "components": components or [],
            },
        }
        return self._post(payload)
