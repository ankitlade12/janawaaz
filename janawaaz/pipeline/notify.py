"""Alert composition, Sarvam translation, Telegram delivery.

Both external services degrade gracefully: without keys the alert text is built
and stored (status stays "pending"), so the pipeline is runnable end-to-end in dev.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import select

from janawaaz.config import settings
from janawaaz.models import Alert, Document, MatchLedger, User

log = logging.getLogger(__name__)

SARVAM_TRANSLATE_URL = "https://api.sarvam.ai/translate"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
# Sarvam language codes are BCP-47-ish with -IN suffix.
SARVAM_LANG = {"hi": "hi-IN", "mr": "mr-IN", "en": "en-IN"}

CONNECT_MESSAGES = {
    "en": "✅ JanAwaaz alerts are connected. Send /stop anytime to unsubscribe.",
    "hi": "✅ JanAwaaz अलर्ट जुड़ गए हैं। सदस्यता बंद करने के लिए कभी भी /stop भेजें।",
    "mr": "✅ JanAwaaz सूचना जोडल्या आहेत. सदस्यता थांबवण्यासाठी कधीही /stop पाठवा.",
}

STOP_MESSAGES = {
    "en": "JanAwaaz alerts are off. Your profile management link can reconnect them.",
    "hi": "JanAwaaz अलर्ट बंद हैं। आपका प्रोफाइल मैनेजमेंट लिंक उन्हें फिर से जोड़ सकता है।",
    "mr": "JanAwaaz सूचना बंद आहेत. तुमची प्रोफाइल मॅनेजमेंट लिंक त्यांना पुन्हा जोडू शकते.",
}

NO_MATCH_MESSAGES = {
    "en": "No verified open matches yet. JanAwaaz will message you when a relevant consultation is still open for comments.",
    "hi": "अभी कोई सत्यापित खुला मैच नहीं है। जब कोई संबंधित परामर्श टिप्पणियों के लिए खुला होगा, JanAwaaz आपको संदेश भेजेगा।",
    "mr": "अजून कोणताही सत्यापित खुला जुळणारा परामर्श नाही. संबंधित परामर्श टिप्पण्यांसाठी खुला असेल तेव्हा JanAwaaz तुम्हाला संदेश पाठवेल.",
}


@dataclass(frozen=True)
class TranslationResult:
    text: str
    translated: bool
    provider: str | None = None
    request_id: str | None = None


def days_remaining(deadline: date | None) -> int | None:
    if deadline is None:
        return None
    return (deadline - datetime.now(timezone.utc).date()).days


def localized_message(kind: str, lang: str | None) -> str:
    catalogs = {
        "connect": CONNECT_MESSAGES,
        "stop": STOP_MESSAGES,
        "no_match": NO_MATCH_MESSAGES,
    }
    catalog = catalogs[kind]
    return catalog.get(lang or "en") or catalog["en"]


def build_alert_text(doc: Document, ledger: MatchLedger) -> str:
    """English alert. Deadline honesty: unverified extraction says so explicitly."""
    lines = [f"🏛️ Your government is asking for your opinion:", f"“{doc.title}”", ""]
    if doc.summary_en:
        lines += [doc.summary_en, ""]
    left = days_remaining(doc.deadline)
    if doc.deadline and doc.deadline_verified:
        when = doc.deadline.strftime("%d %b %Y")
        lines.append(
            f"⏳ Comments close {when}" + (f" — {left} days left." if left is not None and left >= 0 else ".")
        )
    elif doc.deadline:
        lines.append(f"⏳ Deadline (unverified — check source): {doc.deadline.strftime('%d %b %Y')}")
    else:
        lines.append("⏳ Deadline not stated on the document — check the source page.")
    if doc.comment_channel:
        lines.append(f"✍️ Comment here: {doc.comment_channel}")
    if ledger.evidence_span and ledger.span_verified:
        lines += ["", f"Why you: “{ledger.evidence_span}”", "(quoted from the consultation document)"]
    return "\n".join(lines)


def translate_with_metadata(text: str, lang: str) -> TranslationResult:
    """Translate through Sarvam and retain a provider request receipt."""
    cfg = settings()
    if lang == "en" or not cfg.sarvam_api_key:
        return TranslationResult(text=text, translated=False)
    resp = httpx.post(
        SARVAM_TRANSLATE_URL,
        headers={"api-subscription-key": cfg.sarvam_api_key},
        json={
            "input": text,
            "source_language_code": "en-IN",
            "target_language_code": SARVAM_LANG.get(lang, "hi-IN"),
            "model": "sarvam-translate:v1",
        },
        timeout=cfg.http_timeout_seconds,
    )
    resp.raise_for_status()
    data = resp.json()
    translated = data.get("translated_text") or text
    return TranslationResult(
        text=translated,
        translated=translated != text,
        provider="Sarvam AI" if translated != text else None,
        request_id=data.get("request_id"),
    )


def translate(text: str, lang: str) -> str:
    """Delivery-path convenience wrapper around the receipted translation call."""
    return translate_with_metadata(text, lang).text


def tts(text: str, lang: str) -> bytes | None:
    """Sarvam Bulbul TTS -> WAV bytes. Voice alerts reach users who can't read
    the alert — the accessibility half of the vernacular story."""
    cfg = settings()
    if not cfg.sarvam_api_key:
        return None
    import base64

    resp = httpx.post(
        SARVAM_TTS_URL,
        headers={"api-subscription-key": cfg.sarvam_api_key},
        json={
            "text": text[:1500],
            "target_language_code": SARVAM_LANG.get(lang, "hi-IN"),
            "speaker": cfg.sarvam_tts_speaker,
            "model": "bulbul:v2",
        },
        timeout=cfg.http_timeout_seconds,
    )
    resp.raise_for_status()
    audios = resp.json().get("audios") or []
    return base64.b64decode(audios[0]) if audios else None


def telegram_send_audio(chat_id: str, audio_wav: bytes, caption: str = "") -> bool:
    cfg = settings()
    if not cfg.telegram_bot_token:
        return False
    resp = httpx.post(
        f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendAudio",
        data={"chat_id": chat_id, "caption": caption[:1000], "title": "JanAwaaz alert"},
        files={"audio": ("alert.wav", audio_wav, "audio/wav")},
        timeout=cfg.http_timeout_seconds * 2,
    )
    ok = resp.status_code == 200 and resp.json().get("ok") is True
    if not ok:
        log.error("telegram sendAudio failed: %s %s", resp.status_code, resp.text[:300])
    return ok


def telegram_send(chat_id: str, text: str) -> bool:
    cfg = settings()
    if not cfg.telegram_bot_token:
        log.info("telegram not configured; alert stored as pending")
        return False
    resp = httpx.post(
        f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=cfg.http_timeout_seconds,
    )
    ok = resp.status_code == 200 and resp.json().get("ok") is True
    if not ok:
        log.error("telegram send failed: %s %s", resp.status_code, resp.text[:300])
    return ok


def send_alert(session, doc: Document, user: User, ledger: MatchLedger) -> Alert:
    """Compose, translate, deliver (Tier 1 only — enforced by the caller)."""
    existing = session.execute(
        select(Alert).where(Alert.ledger_id == ledger.id, Alert.channel == "telegram")
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    text_en = build_alert_text(doc, ledger)
    lang = user.language or "en"
    payload = translate(text_en, lang)

    alert = Alert(ledger_id=ledger.id, channel="telegram", payload_translated=payload, language=lang)
    if user.telegram_chat_id and telegram_send(user.telegram_chat_id, payload):
        alert.status = "sent"
        alert.sent_at = datetime.now(timezone.utc)
        if settings().voice_alerts and lang in ("hi", "mr"):
            try:
                audio = tts(payload, lang)
                if audio:
                    telegram_send_audio(user.telegram_chat_id, audio, caption=doc.title[:200])
            except Exception:  # voice is best-effort; the text alert already landed
                log.exception("voice alert failed for user %s", user.id)
    session.add(alert)
    session.flush()
    return alert
