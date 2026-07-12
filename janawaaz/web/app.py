"""JanAwaaz web app.

HTML product surface:
  GET  /              landing (live stats, gate explainer)
  GET  /feed          consultation feed, closing-soonest first (?source= filter)
  GET  /c/{id}        shareable consultation page (summary, deadline evidence,
                      comment CTA, one-tap WhatsApp/Telegram/X share)
  GET  /ledger/{id}   provenance view — why an alert fired (the money shot)
  GET  /onboard       onboarding form; POST /onboard creates the profile

Integration surface for intermediaries (orgs, journalists, associations):
  GET  /feed.rss       RSS 2.0 — plug into any reader/CMS
  GET  /deadlines.ics  subscribable calendar of open comment deadlines

JSON API (same data, machine-shaped):
  POST /api/users · GET /api/feed · GET /api/ledger/{id} · GET /healthz
"""

import base64
import hashlib
import hmac
import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from janawaaz.config import settings
from janawaaz.db import init_db, session
from janawaaz.models import Document, MatchLedger, Source, User
from janawaaz.pipeline import notify, runner, summarize
from janawaaz.pipeline.notify import days_remaining

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="JanAwaaz", version="0.3.0", lifespan=_lifespan)

_BASE = Path(__file__).parent
templates = Jinja2Templates(directory=_BASE / "templates")
app.mount("/static", StaticFiles(directory=_BASE / "static"), name="static")


def _plaintext(value: str | None) -> str:
    """Flatten LLM markdown (bold, headings, bullets) into clean prose for cards."""
    if not value:
        return ""
    lowered = value.lower()
    if any(marker in lowered for marker in (
        "captcha", "security check", "enable javascript", "cannot summarize",
        "can't summarize", "unable to summarize", "could not be summarized",
    )):
        return ""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


templates.env.filters["plaintext"] = _plaintext

LANGUAGE_LABELS = {"en": "English", "hi": "Hindi (हिन्दी)", "mr": "Marathi (मराठी)"}


# --------------------------------------------------------------------------- HTML

@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    with session() as s:
        stats = {
            "documents": s.execute(select(func.count()).select_from(Document)).scalar() or 0,
            "sources": s.execute(select(func.count()).select_from(Source)).scalar() or 0,
            "decisions": s.execute(select(func.count()).select_from(MatchLedger)).scalar() or 0,
            "languages": 3,
        }
        demo_rows = s.execute(
            select(MatchLedger, Document, Source.adapter)
            .join(Document, MatchLedger.document_id == Document.id)
            .join(Source, Document.source_id == Source.id)
            .where(MatchLedger.tier.in_([1, 3]))
            .order_by(MatchLedger.created_at.desc())
        ).all()
        examples = {}
        for row, doc, source_name in demo_rows:
            examples.setdefault(
                row.tier,
                {
                    "id": row.id,
                    "title": doc.title,
                    "summary": doc.summary_en,
                    "deadline": doc.deadline,
                    "evidence": row.evidence_span,
                    "source": source_name.upper(),
                    "tier": row.tier,
                },
            )
    return templates.TemplateResponse(
        request, "landing.html", {"stats": stats, "examples": examples}
    )


def _feed_rows(source_filter: str | None, limit: int = 100):
    with session() as s:
        q = (
            select(Document, Source.adapter)
            .join(Source, Document.source_id == Source.id)
            .order_by(Document.published_at.desc().nulls_last())
            .limit(limit)
        )
        if source_filter:
            q = q.where(Source.adapter == source_filter)
        rows = s.execute(q).all()
        sources = sorted(s.execute(select(Source.adapter)).scalars().all())

    # Actionability ordering: open consultations closing soonest come first,
    # then everything else by recency — "what can I still act on?"
    today = date.today()
    far = date.max

    def sort_key(row):
        d, _ = row
        actionable = d.deadline is not None and d.deadline >= today
        return (
            0 if actionable else 1,
            d.deadline if actionable else far,
            -(d.published_at or date.min).toordinal(),
        )

    rows.sort(key=sort_key)
    return rows, sources


def _effective_status(doc: Document) -> str:
    if doc.deadline and doc.deadline < date.today():
        return "closed"
    if doc.deadline and doc.deadline >= date.today():
        return "open"
    return doc.status


@app.get("/feed", response_class=HTMLResponse)
def feed_page(request: Request, source: str | None = None):
    rows, sources = _feed_rows(source)
    items = [
        {
            "id": d.id,
            "source": adapter,
            "title": d.title,
            "ministry": d.ministry,
            "summary_en": d.summary_en,
            "published_at": d.published_at,
            "deadline": d.deadline,
            "deadline_verified": d.deadline_verified,
            "days_remaining": days_remaining(d.deadline),
            "comment_channel": d.comment_channel,
            "body_url": d.body_url,
            "status": _effective_status(d),
        }
        for d, adapter in rows
    ]
    return templates.TemplateResponse(
        request, "feed.html", {"items": items, "sources": sources, "source_filter": source}
    )


@app.get("/c/{doc_id}", response_class=HTMLResponse)
def consultation_page(request: Request, doc_id: int):
    """Shareable per-consultation page — the broadcast unit for intermediaries."""
    from urllib.parse import quote

    with session() as s:
        doc = s.get(Document, doc_id)
        if doc is None:
            raise HTTPException(404, "no such consultation")
        source_name = s.get(Source, doc.source_id).adapter

    page_url = f"https://janawaaz-web.onrender.com/c/{doc.id}"
    left = days_remaining(doc.deadline)
    share_bits = [f"Your government is asking: “{doc.title}”"]
    if doc.deadline and left is not None and left >= 0:
        share_bits.append(f"Comments close {doc.deadline.strftime('%d %b %Y')} ({left} days left).")
    share_bits.append(page_url)
    share_text = quote(" ".join(share_bits))

    return templates.TemplateResponse(
        request,
        "consultation.html",
        {
            "doc": doc,
            "source_name": source_name,
            "days_remaining": left,
            "share_whatsapp": f"https://wa.me/?text={share_text}",
            "share_telegram": f"https://t.me/share/url?url={quote(page_url)}&text={share_text}",
            "share_x": f"https://twitter.com/intent/tweet?text={share_text}",
        },
    )


@app.get("/feed.rss")
def feed_rss():
    """RSS 2.0 of tracked consultations — for readers, CMSes, org workflows."""
    from email.utils import format_datetime
    from datetime import datetime, time as dtime, timezone
    from xml.sax.saxutils import escape

    rows, _ = _feed_rows(None, limit=50)
    items = []
    for d, adapter in rows:
        link = f"https://janawaaz-web.onrender.com/c/{d.id}"
        desc_parts = []
        if d.deadline:
            state = "verified" if d.deadline_verified else "unverified — check source"
            desc_parts.append(f"Comments close {d.deadline.strftime('%d %b %Y')} ({state}).")
        if d.summary_en:
            desc_parts.append(_plaintext(d.summary_en))
        pub = format_datetime(
            datetime.combine(d.published_at or date.today(), dtime(9, 0), tzinfo=timezone.utc)
        )
        items.append(
            f"<item><title>{escape(f'[{adapter.upper()}] {d.title}')}</title>"
            f"<link>{escape(link)}</link><guid isPermaLink=\"true\">{escape(link)}</guid>"
            f"<pubDate>{pub}</pubDate>"
            f"<description>{escape(' '.join(desc_parts))}</description></item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        "<title>JanAwaaz — open government consultations</title>"
        "<link>https://janawaaz-web.onrender.com/feed</link>"
        "<description>Consultations tracked by JanAwaaz, closing-soonest first, "
        "with span-verified deadlines.</description>" + "".join(items) + "</channel></rss>"
    )
    return Response(content=xml, media_type="application/rss+xml")


@app.get("/deadlines.ics")
def deadlines_ics():
    """Subscribable calendar of open comment deadlines — orgs live in calendars."""
    rows, _ = _feed_rows(None, limit=200)
    today = date.today()
    events = []
    for d, adapter in rows:
        if not d.deadline or d.deadline < today:
            continue
        day = d.deadline.strftime("%Y%m%d")
        title = f"Comments close: {d.title[:120]}"
        events.append(
            "BEGIN:VEVENT\r\n"
            f"UID:doc{d.id}@janawaaz\r\n"
            f"DTSTART;VALUE=DATE:{day}\r\n"
            f"SUMMARY:{_ics_escape(f'[{adapter.upper()}] {title}')}\r\n"
            f"DESCRIPTION:{_ics_escape(f'https://janawaaz-web.onrender.com/c/{d.id}')}\r\n"
            "END:VEVENT\r\n"
        )
    cal = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//JanAwaaz//consultation deadlines//EN\r\n"
        "X-WR-CALNAME:JanAwaaz consultation deadlines\r\n" + "".join(events) + "END:VCALENDAR\r\n"
    )
    return Response(content=cal, media_type="text/calendar")


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


@app.get("/ledger/{ledger_id}", response_class=HTMLResponse)
def ledger_page(request: Request, ledger_id: int):
    with session() as s:
        row = s.get(MatchLedger, ledger_id)
        if row is None:
            raise HTTPException(404, "no such ledger entry")
        doc = s.get(Document, row.document_id)
        source_name = s.get(Source, doc.source_id).adapter
    return templates.TemplateResponse(
        request,
        "ledger.html",
        {
            "row": row,
            "doc": doc,
            "source_name": source_name,
            "threshold": settings().similarity_threshold,
            "sim_passed": row.similarity >= settings().similarity_threshold,
        },
    )


@app.get("/onboard", response_class=HTMLResponse)
def onboard_form(request: Request):
    return templates.TemplateResponse(request, "onboard.html", {})


@app.post("/onboard")
def onboard_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    name: str = Form(..., max_length=200),
    language: str = Form("en"),
    interests_text: str = Form(..., min_length=10, max_length=2000),
):
    if language not in LANGUAGE_LABELS:
        language = "en"
    with session() as s:
        user = User(
            name=name.strip(),
            language=language,
            interests_text=interests_text.strip(),
            telegram_chat_id=None,
            embedding=summarize.embed(interests_text),
        )
        s.add(user)
        s.flush()
        uid = user.id
    # Run after returning the consent page: verifier calls must not make signup
    # wait, but the user still gets checked without waiting for a future paper.
    background_tasks.add_task(_match_user_background, uid)
    token = _signed_token(uid, "manage")
    return RedirectResponse(f"/onboard/done?uid={uid}&token={token}", status_code=303)


@app.get("/onboard/done", response_class=HTMLResponse)
def onboard_done(request: Request, uid: int, token: str):
    _require_token(uid, "manage", token)
    with session() as s:
        user = s.get(User, uid)
        if user is None:
            raise HTTPException(404)
        ctx = {
            "name": user.name,
            "language_label": LANGUAGE_LABELS.get(user.language, "English"),
            "has_telegram": bool(user.telegram_chat_id),
            "telegram_link": _telegram_link(user.id),
            "manage_token": token,
            "uid": user.id,
        }
    return templates.TemplateResponse(request, "onboarded.html", ctx)


# --------------------------------------------------------------------------- JSON API

class UserIn(BaseModel):
    name: str = Field(..., max_length=200)
    language: str = Field("en", pattern="^(en|hi|mr)$")
    interests_text: str = Field(..., min_length=10, max_length=2000)


class UserOut(BaseModel):
    id: int
    name: str
    language: str


@app.post("/api/users", response_model=UserOut, status_code=201)
def api_create_user(payload: UserIn, background_tasks: BackgroundTasks) -> UserOut:
    with session() as s:
        user = User(
            name=payload.name,
            language=payload.language,
            interests_text=payload.interests_text,
            telegram_chat_id=None,
            embedding=summarize.embed(payload.interests_text),
        )
        s.add(user)
        s.flush()
        uid = user.id
        result = UserOut(id=user.id, name=user.name, language=user.language)
    background_tasks.add_task(_match_user_background, uid)
    return result


class FeedItem(BaseModel):
    id: int
    source: str
    title: str
    ministry: str | None
    summary_en: str | None
    published_at: date | None
    deadline: date | None
    deadline_verified: bool
    days_remaining: int | None
    comment_channel: str | None
    status: str


@app.get("/api/feed", response_model=list[FeedItem])
def api_feed(source: str | None = None, limit: int = 50) -> list[FeedItem]:
    rows, _ = _feed_rows(source, limit=min(limit, 200))
    return [
        FeedItem(
            id=d.id,
            source=adapter,
            title=d.title,
            ministry=d.ministry,
            summary_en=d.summary_en,
            published_at=d.published_at,
            deadline=d.deadline,
            deadline_verified=d.deadline_verified,
            days_remaining=days_remaining(d.deadline),
            comment_channel=d.comment_channel,
            status=_effective_status(d),
        )
        for d, adapter in rows
    ]


class LedgerOut(BaseModel):
    id: int
    document_id: int
    document_title: str
    user_id: int
    similarity: float
    verifier_verdict: str | None
    verifier_reason: str | None
    evidence_span: str | None
    span_verified: bool | None
    tier: int
    tier_label: str
    deadline: date | None
    deadline_span: str | None


TIER_LABELS = {1: "confirmed", 2: "possible", 3: "rejected"}


@app.get("/api/ledger/{ledger_id}", response_model=LedgerOut)
def api_ledger(ledger_id: int) -> LedgerOut:
    with session() as s:
        row = s.get(MatchLedger, ledger_id)
        if row is None:
            raise HTTPException(404, "no such ledger entry")
        doc = s.get(Document, row.document_id)
        return LedgerOut(
            id=row.id,
            document_id=doc.id,
            document_title=doc.title,
            user_id=row.user_id,
            similarity=row.similarity,
            verifier_verdict=row.verifier_verdict,
            verifier_reason=row.verifier_reason,
            evidence_span=row.evidence_span,
            span_verified=row.span_verified,
            tier=row.tier,
            tier_label=TIER_LABELS.get(row.tier, "unknown"),
            deadline=doc.deadline,
            deadline_span=doc.deadline_span,
        )


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


# ---------------------------------------------------------------- Telegram consent + profile controls

def _match_user_background(uid: int) -> None:
    """Backfill actionable consultations after signup without blocking the form."""
    with session() as s:
        user = s.get(User, uid)
        if user is not None and user.active and user.embedding is not None:
            runner.match_existing_for_user(s, user, skip_notify=False)

def _secret() -> bytes:
    cfg = settings()
    secret = cfg.app_secret or cfg.telegram_bot_token
    if not secret:
        # Stable local-dev fallback. Production deployment docs require APP_SECRET.
        secret = "janawaaz-local-development-only"
    return secret.encode()


def _signed_token(uid: int, purpose: str) -> str:
    payload = f"{uid}:{purpose}".encode()
    sig = hmac.new(_secret(), payload, hashlib.sha256).digest()[:18]
    return base64.urlsafe_b64encode(payload + b":" + sig).decode().rstrip("=")


def _verify_token(token: str, purpose: str) -> int | None:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        uid_raw, got_purpose, sig = raw.split(b":", 2)
        payload = uid_raw + b":" + got_purpose
        expected = hmac.new(_secret(), payload, hashlib.sha256).digest()[:18]
        if got_purpose.decode() != purpose or not hmac.compare_digest(sig, expected):
            return None
        return int(uid_raw)
    except (ValueError, UnicodeDecodeError):
        return None


def _require_token(uid: int, purpose: str, token: str) -> None:
    if _verify_token(token, purpose) != uid:
        raise HTTPException(403, "invalid or expired profile link")


def _telegram_link(uid: int) -> str:
    cfg = settings()
    token = _signed_token(uid, "telegram")
    return f"https://t.me/{cfg.telegram_bot_username}?start={token}"


@app.post("/api/telegram/webhook")
def telegram_webhook(
    update: dict,
    x_telegram_bot_api_secret_token: str | None = Header(None),
) -> dict:
    cfg = settings()
    if cfg.telegram_webhook_secret and not hmac.compare_digest(
        x_telegram_bot_api_secret_token or "", cfg.telegram_webhook_secret
    ):
        raise HTTPException(403, "invalid Telegram webhook secret")
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    text = str(message.get("text") or "")
    if text.strip().lower() == "/stop" and chat.get("id"):
        with session() as s:
            user = s.execute(
                select(User).where(User.telegram_chat_id == str(chat["id"]))
            ).scalar_one_or_none()
            if user:
                user.telegram_chat_id = None
                user.active = False
        notify.telegram_send(str(chat["id"]), "JanAwaaz alerts are off. Your profile management link can reconnect them.")
        return {"ok": True}
    if not text.startswith("/start ") or not chat.get("id"):
        return {"ok": True}
    token = text.split(maxsplit=1)[1].strip()
    uid = _verify_token(token, "telegram")
    if uid is None:
        return {"ok": True}
    with session() as s:
        user = s.get(User, uid)
        if user is None or user.interests_text == "Deleted by user request":
            return {"ok": True}
        user.active = True
        user.telegram_chat_id = str(chat["id"])
        # Deliver confirmed decisions created during onboarding. send_alert is
        # idempotent, so Telegram webhook retries cannot duplicate them.
        rows = s.execute(
            select(MatchLedger, Document)
            .join(Document, MatchLedger.document_id == Document.id)
            .where(MatchLedger.user_id == uid, MatchLedger.tier == 1)
        ).all()
        for ledger, doc in rows:
            notify.send_alert(s, doc, user, ledger)
    notify.telegram_send(str(chat["id"]), "✅ JanAwaaz alerts are connected. Send /stop anytime to unsubscribe.")
    return {"ok": True}


@app.post("/profile/{uid}/unsubscribe")
def unsubscribe(uid: int, token: str = Form(...)):
    _require_token(uid, "manage", token)
    with session() as s:
        user = s.get(User, uid)
        if user is None:
            raise HTTPException(404)
        user.telegram_chat_id = None
        user.active = False
    return RedirectResponse("/", status_code=303)


@app.post("/profile/{uid}/delete")
def delete_profile(uid: int, token: str = Form(...)):
    """Privacy-preserving deletion while retaining anonymous audit decisions."""
    _require_token(uid, "manage", token)
    with session() as s:
        user = s.get(User, uid)
        if user is None:
            raise HTTPException(404)
        user.name = "Deleted user"
        user.interests_text = "Deleted by user request"
        user.embedding = None
        user.telegram_chat_id = None
        user.active = False
    return RedirectResponse("/", status_code=303)
