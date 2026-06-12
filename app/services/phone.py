"""MSISDN normalisation to E.164, Malaysia-first."""
import re


def normalize_msisdn(raw: str | None, default_country: str = "60") -> str | None:
    """Normalise messy phone input to E.164 (+60...). Returns None if unusable.

    Handles: '012-345 6789', '60123456789', '+60 12 345 6789', '0060123...'.
    Non-Malaysian numbers in full international format are kept as-is.
    """
    if not raw:
        return None
    cleaned = re.sub(r"[^\d+]", "", str(raw).strip())
    if not cleaned:
        return None
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if cleaned.startswith("00"):
        cleaned = cleaned[2:]
    if cleaned.startswith("0"):  # local format e.g. 0123456789
        cleaned = default_country + cleaned[1:]
    if not cleaned.isdigit():
        return None
    if not 9 <= len(cleaned) <= 15:
        return None
    return f"+{cleaned}"
