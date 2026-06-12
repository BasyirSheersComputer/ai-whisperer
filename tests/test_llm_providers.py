"""LLM provider routing: Gemini default, Anthropic switch, dry-run fallback."""
import json

import app.services.llm as llm_mod
from app.config import Settings
from app.services.llm import Classification, classify, respond, use_dry_run


class FakeResponse:
    def __init__(self, text: str):
        self._text = text
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": self._text}]}}]}


def _gemini_settings(**over):
    base = dict(llm_provider="gemini", gemini_api_key="g-key", llm_dry_run=False, debug=True)
    base.update(over)
    return Settings(**base)


def test_dry_run_when_no_key_for_active_provider(monkeypatch):
    monkeypatch.setattr(llm_mod, "get_settings", lambda: _gemini_settings(gemini_api_key=""))
    assert use_dry_run() is True
    # Anthropic key present is irrelevant when provider is gemini
    monkeypatch.setattr(llm_mod, "get_settings",
                        lambda: _gemini_settings(gemini_api_key="", anthropic_api_key="a-key"))
    assert use_dry_run() is True


def test_gemini_classify_parses_json_and_hits_correct_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        return FakeResponse('{"intent": "question", "language": "ms", "entities": {}}')

    monkeypatch.setattr(llm_mod, "get_settings", lambda: _gemini_settings())
    monkeypatch.setattr(llm_mod.httpx, "post", fake_post)

    result = classify("berapa harga sebulan?")
    assert result.intent == "question"
    assert result.language == "ms"
    assert "gemini-3.1-flash-lite:generateContent" in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "g-key"
    assert captured["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_respond_maps_history_roles(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["body"] = json
        return FakeResponse("Boleh! Nak datang bila?")

    monkeypatch.setattr(llm_mod, "get_settings", lambda: _gemini_settings())
    monkeypatch.setattr(llm_mod.httpx, "post", fake_post)

    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello!"},
        {"role": "user", "content": "boleh tanya?"},
    ]
    reply = respond("system prompt", history, Classification(intent="question"), None)
    assert reply == "Boleh! Nak datang bila?"
    assert "gemini-3.5-flash:generateContent" in captured["url"]
    roles = [c["role"] for c in captured["body"]["contents"]]
    assert roles == ["user", "model", "user"]
    assert captured["body"]["system_instruction"]["parts"][0]["text"] == "system prompt"


def test_gemini_unparseable_classifier_output_degrades_to_unclear(monkeypatch):
    monkeypatch.setattr(llm_mod, "get_settings", lambda: _gemini_settings())
    monkeypatch.setattr(llm_mod.httpx, "post",
                        lambda *a, **k: FakeResponse("sorry I cannot do JSON today"))
    assert classify("hello").intent == "unclear"


def test_anthropic_provider_still_selectable(monkeypatch):
    s = Settings(llm_provider="anthropic", anthropic_api_key="", llm_dry_run=False, debug=True)
    monkeypatch.setattr(llm_mod, "get_settings", lambda: s)
    assert use_dry_run() is True  # no key -> heuristics, no crash
    assert classify("ok can").intent == "positive"
