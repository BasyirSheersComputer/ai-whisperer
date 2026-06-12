"""LLM layer: intent classifier + responder (plan §7), provider-pluggable.

Providers:
- gemini (default): Google Gemini via REST generateContent — no SDK needed.
- anthropic: Claude (classifier=Haiku, responder=Sonnet).

Dry-run mode (default, or whenever the selected provider has no API key) swaps
API calls for deterministic heuristics so dev and tests run with zero keys.
The opt-out path never reaches this module at all — see services.lexicon.
"""
import json
import logging
from dataclasses import dataclass, field

import httpx

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


# ---------- dry-run heuristics ----------

def _dry_run_classify(text: str) -> Classification:
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


# ---------- provider plumbing ----------

def use_dry_run() -> bool:
    s = get_settings()
    if s.llm_dry_run:
        return True
    if s.llm_provider == "gemini":
        return not s.gemini_api_key
    return not s.anthropic_api_key


def _models() -> tuple[str, str]:
    """(classifier_model, responder_model) for the active provider."""
    s = get_settings()
    if s.llm_provider == "gemini":
        return s.gemini_classifier_model, s.gemini_responder_model
    return s.anthropic_classifier_model, s.anthropic_responder_model


def _gemini_generate(model: str, system: str, contents: list[dict], max_tokens: int, force_json: bool = False) -> str:
    s = get_settings()
    generation_config: dict = {"maxOutputTokens": max_tokens}
    if force_json:
        generation_config["responseMimeType"] = "application/json"
    resp = httpx.post(
        f"{s.gemini_base_url}/models/{model}:generateContent",
        headers={"x-goog-api-key": s.gemini_api_key, "Content-Type": "application/json"},
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": generation_config,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _anthropic_generate(model: str, system: str, messages: list[dict], max_tokens: int) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    resp = client.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages)
    return resp.content[0].text.strip()


def _to_gemini_contents(history: list[dict]) -> list[dict]:
    """Anthropic-style [{role: user|assistant, content}] -> Gemini contents."""
    return [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in history
    ]


def _generate(system: str, history: list[dict], model: str, max_tokens: int, force_json: bool = False) -> str:
    if get_settings().llm_provider == "gemini":
        return _gemini_generate(model, system, _to_gemini_contents(history), max_tokens, force_json)
    return _anthropic_generate(model, system, history, max_tokens)


# ---------- public API ----------

def classify(text: str) -> Classification:
    if use_dry_run():
        return _dry_run_classify(text)

    classifier_model, _ = _models()
    raw = _generate(CLASSIFIER_SYSTEM, [{"role": "user", "content": text}],
                    classifier_model, max_tokens=200, force_json=True)
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
    except (json.JSONDecodeError, AttributeError, IndexError, KeyError):
        logger.warning("Classifier returned unparseable output: %r", raw)
        return Classification(intent="unclear")


def respond(system_prompt: str, history: list[dict], classification: Classification, booking_url: str | None) -> str:
    if use_dry_run():
        return _dry_run_respond(classification, booking_url)

    _, responder_model = _models()
    return _generate(system_prompt, history, responder_model, max_tokens=300)
