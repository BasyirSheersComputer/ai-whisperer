"""M5 calendar layer: Cal.com provider with dry-run slots.

Dry-run (default / no API key) returns deterministic next-day MYT slots so the
whole booking flow works before a client connects a real calendar.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

MYT = timezone(timedelta(hours=8))


@dataclass
class Slot:
    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        local = self.start.astimezone(MYT)
        hour12 = local.strftime("%I").lstrip("0") or "12"  # %-I is not portable to Windows
        return local.strftime(f"%a %d %b, {hour12}:%M%p").replace("AM", "am").replace("PM", "pm")

    @property
    def iso(self) -> str:
        return self.start.isoformat()


class CalComProvider:
    def __init__(self) -> None:
        s = get_settings()
        self.api_key = s.calcom_api_key
        self.base = s.calcom_base_url
        self.dry_run = s.calendar_dry_run or not self.api_key

    def get_slots(self, event_slug: str | None, n: int = 3, now: datetime | None = None) -> list[Slot]:
        now = now or datetime.now(timezone.utc)
        if self.dry_run:
            tomorrow_myt = (now.astimezone(MYT) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
            slots = []
            for hour in (10, 14, 18)[:n]:
                start = tomorrow_myt.replace(hour=hour).astimezone(timezone.utc)
                slots.append(Slot(start=start, end=start + timedelta(hours=1)))
            return slots
        resp = httpx.get(
            f"{self.base}/slots",
            params={"eventTypeSlug": event_slug, "start": now.isoformat(),
                    "end": (now + timedelta(days=7)).isoformat()},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        out: list[Slot] = []
        for day_slots in resp.json().get("data", {}).get("slots", {}).values():
            for s_ in day_slots:
                start = datetime.fromisoformat(s_["start"].replace("Z", "+00:00"))
                out.append(Slot(start=start, end=start + timedelta(hours=1)))
                if len(out) >= n:
                    return out
        return out

    def create_booking(self, event_slug: str | None, slot: Slot, name: str | None, phone: str) -> str:
        if self.dry_run:
            ext_id = f"calcom.DRYRUN.{uuid.uuid4().hex[:12]}"
            logger.info("[DRY RUN] Cal.com booking %s at %s for %s", ext_id, slot.iso, phone)
            return ext_id
        resp = httpx.post(
            f"{self.base}/bookings",
            json={"eventTypeSlug": event_slug, "start": slot.iso,
                  "attendee": {"name": name or phone, "timeZone": "Asia/Kuala_Lumpur",
                               "phoneNumber": phone}},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        return str(resp.json().get("data", {}).get("uid", ""))
