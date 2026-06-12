"""LLM layer: Haiku classifier + Sonnet responder (plan §7).

Dry-run mode (default, or whenever no API key is set) swaps API calls for
deterministic heuristics so dev and tests run with zero keys/cost. The opt-out
path never reaches this module at all — see services.lexicon.
"""
import json
import logging
from dataclasses import dataclass, field

from app.config import get_settings
from app.services import lexicon
from app.services.prompts import CLASSIFIER_SYSTEM

logger = logging.getLogger(__name__)

VALID_INTENTS = {"positive", "question", "negative_soft", "opt_out", "request_human", "unclear"}


@dataclass
class Classification:
    intent: str
    language: str = "en"
    entities: dict = field(default_factory=dict)


def _dry_run_classify(text: str) -> Classification:
    """Deterministic heuristic classifier for dev/tests."""
    norm = text.strip().lower()
    if lexicon.is_opt_out(norm):
        return Classification(intent="opt_out")
    if lexicon.is_human_request(norm):
        return Classification(intent="request_human")
    if "?" in norm or any(w in norm for w in ("how much", "berapa", "price", "harga", "bila", "when", "where", "mana", "几点", "多少")):
        return Classification(intent="question")
    if any(w in norm for w in ("yes", "ok", "sure", "can", "boleh", "nak", "interested", "set", "好", "要")):
        return Classification(intent="positive")
    if any(w in norm for w in ("no thanks", "not now", "maybe later", "next time", "lain kali", "busy")):
        return Classification(intent="negative_soft")
    return Classification(intent="unclear")


def _dry_run_respond(classification: Classification, booking_url: str | None) -> str:
    if classification.intent == "question":
        return "Good question! Let me get you the details — meanwhile, want me to hold a slot for you?"
    if classification.intent == "positive":
        link = booking_url or "our booking page"
        return f"Awesome! You can grab a time here: {link}"
    if classification.intent == "negative_soft":
        return "No worries at all! We're here whenever you're ready."
    return "Hey! Just checking — are you still keen? Happy to help with any questions."


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


def _use_dry_run() -> bool:
    s = get_settings()
    return s.llm_dry_run or not s.anthropic_api_key


def classify(text: str) -> Classification:
    if _use_dry_run():
        return _dry_run_classify(text)

    s = get_settings()
    resp = _client().messages.create(
        model=s.classifier_model,
        max_tokens=200,
        system=CLASSIFIER_SYSTEM,
        messages=[{"role": "user", "content": text}],
    )
    raw = resp.content[0].text.strip()
    try:
        if raw.startswith("```"):
            raw = raw.strip("`").removeprefix("json").strip()
        data = json.loads(raw)
        intent = data.get("intent", "unclear")
        if intent not in VALID_INTENTS:
            intent = "unclear"
        return Classification(
            intent=intent,
            language=data.get("language", "en"),
            entities=data.get("entities") or {},
        )
    except (json.JSONDecodeError, AttributeError, IndexError):
        logger.warning("Classifier returned unparseable output: %r", raw)
        return Classification(intent="unclear")


def respond(system_prompt: str, history: list[dict], classification: Classification, booking_url: str | None) -> str:
    if _use_dry_run():
        return _dry_run_respond(classification, booking_url)

    s = get_settings()
    resp = _client().messages.create(
        model=s.responder_model,
        max_tokens=300,
        system=system_prompt,
        messages=history,
    )
    return resp.content[0].text.strip()
