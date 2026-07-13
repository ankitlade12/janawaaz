from datetime import date, timedelta

from janawaaz.models import Document
from janawaaz.pipeline.extract import is_challenge_text
from janawaaz.pipeline.summarize import _clean_summary
from janawaaz.pipeline import notify
from janawaaz.web.app import _effective_status, _signed_token, _verify_token


def test_antibot_challenge_is_detected_before_summarization():
    text = (
        "Please enable JavaScript to view the page content. "
        "Enter the code shown in the image. Support ID: 12345"
    )
    assert is_challenge_text(text)


def test_normal_consultation_text_is_not_a_challenge():
    assert not is_challenge_text(
        "Stakeholders may submit comments on the proposed tariff rules by 20 August 2026."
    )


def test_model_failure_message_is_not_published_as_a_summary():
    assert _clean_summary("I cannot summarize this because it is a CAPTCHA security check.") == ""
    assert _clean_summary("The regulator proposes faster complaint resolution.")


def test_summary_markdown_is_normalized_for_alerts():
    raw = "**1) What changes**\n- Faster complaint handling.\n\n(Word count: 4)"
    cleaned = _clean_summary(raw)
    assert "**" not in cleaned and "Word count" not in cleaned
    assert "Faster complaint handling." in cleaned


def test_signed_tokens_are_purpose_bound_and_tamper_evident():
    token = _signed_token(42, "manage")
    assert _verify_token(token, "manage") == 42
    assert _verify_token(token, "telegram") is None
    assert _verify_token(token[:-1] + ("A" if token[-1] != "A" else "B"), "manage") is None


def test_deadline_overrides_stale_source_status():
    doc = Document(
        source_id=1,
        external_id="status-test",
        title="Status test",
        body_url="https://example.test/paper",
        deadline=date.today() - timedelta(days=1),
        status="open",
    )
    assert _effective_status(doc) == "closed"


def test_sarvam_translation_retains_request_receipt(monkeypatch):
    captured = {}

    class Config:
        sarvam_api_key = "test-only-key"
        http_timeout_seconds = 3

    monkeypatch.setattr(notify, "settings", lambda: Config())

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"translated_text": "नमस्ते", "request_id": "sarvam-request-123"}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["headers"] = kwargs["headers"]
        return Response()

    monkeypatch.setattr(notify.httpx, "post", fake_post)
    result = notify.translate_with_metadata("Hello", "hi")

    assert result.text == "नमस्ते"
    assert result.translated and result.provider == "Sarvam AI"
    assert result.request_id == "sarvam-request-123"
    assert captured["url"].endswith("/translate")
    assert captured["json"]["model"] == "sarvam-translate:v1"
    assert captured["json"]["target_language_code"] == "hi-IN"
