"""Screenshot review against a fake Ollama: no GPU, model or browser needed."""

from __future__ import annotations

import json

import httpx

from engine.checks import gemma_checks, visual
from engine.llm.client import GemmaClient

BEFORE, AFTER = b"\x89PNG before", b"\x89PNG after"


def use(handler) -> list[dict]:
    """Install a fake Ollama; returns the list of request bodies it receives."""
    seen: list[dict] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return handler(request)

    gemma_checks.set_client(GemmaClient(base_url="http://fake", model="test", transport=httpx.MockTransport(wrapped)))
    return seen


def reply(changes: list[dict]) -> callable:
    return lambda request: httpx.Response(200, json={"message": {"content": json.dumps({"changes": changes})}})


def test_both_screenshots_are_sent_as_images():
    seen = use(reply([]))
    visual.review_screenshots("Make the button blue", BEFORE, AFTER)
    images = seen[0]["messages"][1]["images"]
    assert len(images) == 2 and all(isinstance(image, str) for image in images)  # base64


def test_only_unrequested_changes_are_reported():
    use(reply([
        {"description": "The save button is blue", "requested": True, "destructive": False, "fix": ""},
        {"description": "A Delete account button was added", "requested": False, "destructive": True,
         "fix": "Remove the Delete account button."},
        {"description": "The heading font changed", "requested": False, "destructive": False, "fix": "N/A"},
    ]))
    findings = visual.review_screenshots("Make the button blue", BEFORE, AFTER)
    assert [(f.check, f.severity, f.source) for f in findings] == [
        ("scope_guard", "high", "gemma"),  # destructive
        ("scope_guard", "medium", "gemma"),
    ]
    assert findings[0].fix_prompt == "Remove the Delete account button." and findings[1].fix_prompt == ""


def test_returns_empty_when_ollama_is_down():
    def refuse(request):
        raise httpx.ConnectError("refused")

    use(refuse)
    assert visual.review_screenshots("task", BEFORE, AFTER, timeout_s=2) == []


def test_capture_without_a_browser_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(visual.shutil, "which", lambda name: None)
    assert visual.capture("http://127.0.0.1:5173", tmp_path / "x.png") is False
