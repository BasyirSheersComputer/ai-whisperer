"""Deterministic multilingual lexicons — checked BEFORE any LLM call.

Opt-out must never depend on an LLM: it is a compliance action (PDPA + Meta
policy), so it short-circuits on exact/substring keyword match in English,
Bahasa Malaysia, and Chinese, the three dominant KL languages.
"""
import re

# Matched as whole message (after normalisation) or standalone phrase.
OPT_OUT_EXACT = {
    "stop",
    "unsubscribe",
    "berhenti",
    "henti",
    "停",
    "停止",
    "不要",
}

# Matched as substring anywhere in the message.
OPT_OUT_PHRASES = [
    "tak nak",
    "taknak",
    "tak mahu",
    "tak mau",
    "jangan mesej",
    "jangan message",
    "jangan contact",
    "jangan hubungi",
    "remove me",
    "delete my number",
    "don't message",
    "dont message",
    "do not message",
    "stop messaging",
    "stop texting",
    "not interested",
    "别再发",
    "不要再发",
    "别发了",
]

HUMAN_REQUEST_PHRASES = [
    "real person",
    "real human",
    "speak to a human",
    "talk to a human",
    "speak to someone",
    "talk to staff",
    "speak to staff",
    "call me",
    "cakap dengan orang",
    "nak cakap dengan",
    "boleh call",
    "真人",
    "人工",
]


def _normalise(text: str) -> str:
    return re.sub(r"[^\w\s一-鿿]", "", text.strip().lower())


def is_opt_out(text: str | None) -> bool:
    if not text:
        return False
    norm = _normalise(text)
    if norm in OPT_OUT_EXACT:
        return True
    return any(p in norm for p in OPT_OUT_PHRASES)


def is_human_request(text: str | None) -> bool:
    if not text:
        return False
    norm = _normalise(text)
    return any(p in norm for p in HUMAN_REQUEST_PHRASES)
