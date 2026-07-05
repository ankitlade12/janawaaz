"""JanAwaaz web app.

HTML product surface:
  GET  /              landing (live stats, gate explainer)
  GET  /feed          consultation feed with deadline chips (?source= filter)
  GET  /ledger/{id}   provenance view — why an alert fired (the money shot)
  GET  /onboard       onboarding form; POST /onboard creates the profile

JSON API (same data, machine-shaped):
  POST /api/users · GET /api/feed · GET /api/ledger/{id} · GET /healthz
"""

import re
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from janawaaz.config import settings
from janawaaz.db import init_db, session
from janawaaz.models import Document, MatchLedger, Source, User
from janawaaz.pipeline import summarize
from janawaaz.pipeline.notify import days_remaining

app = FastAPI(title="JanAwaaz", version="0.2.0")

_BASE = Path(__file__).parent
templates = Jinja2Templates(directory=_BASE / "templates")
app.mount("/static", StaticFiles(directory=_BASE / "static"), name="static")


def _plaintext(value: str | None) -> str:
    """Flatten LLM markdown (bold, headings, bullets) into clean prose for cards."""
    if not value:
        return ""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


templates.env.filters["plaintext"] = _plaintext

LANGUAGE_LABELS = {"en": "English", "hi": "Hindi (हिन्दी)", "mr": "Marathi (मराठी)"}


@app.on_event("startup")
def _startup() -> None:
    init_db()


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
    return templates.TemplateResponse(request, "landing.html", {"stats": stats})


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
    return rows, sources


@app.get("/feed", response_class=HTMLResponse)
def feed_page(request: Request, source: str | None = None):
    rows, sources = _feed_rows(source)
    items = [
        {
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
        }
        for d, adapter in rows
    ]
    return templates.TemplateResponse(
        request, "feed.html", {"items": items, "sources": sources, "source_filter": source}
    )


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
    name: str = Form(..., max_length=200),
    language: str = Form("en"),
    interests_text: str = Form(..., min_length=10, max_length=2000),
    telegram_chat_id: str = Form(""),
):
    if language not in LANGUAGE_LABELS:
        language = "en"
    with session() as s:
        user = User(
            name=name.strip(),
            language=language,
            interests_text=interests_text.strip(),
            telegram_chat_id=telegram_chat_id.strip() or None,
            embedding=summarize.embed(interests_text),
        )
        s.add(user)
        s.flush()
        uid = user.id
    return RedirectResponse(f"/onboard/done?uid={uid}", status_code=303)


@app.get("/onboard/done", response_class=HTMLResponse)
def onboard_done(request: Request, uid: int):
    with session() as s:
        user = s.get(User, uid)
        if user is None:
            raise HTTPException(404)
        ctx = {
            "name": user.name,
            "language_label": LANGUAGE_LABELS.get(user.language, "English"),
            "has_telegram": bool(user.telegram_chat_id),
        }
    return templates.TemplateResponse(request, "onboarded.html", ctx)


# --------------------------------------------------------------------------- JSON API

class UserIn(BaseModel):
    name: str = Field(..., max_length=200)
    language: str = Field("en", pattern="^(en|hi|mr)$")
    interests_text: str = Field(..., min_length=10, max_length=2000)
    telegram_chat_id: str | None = None


class UserOut(BaseModel):
    id: int
    name: str
    language: str


@app.post("/api/users", response_model=UserOut, status_code=201)
def api_create_user(payload: UserIn) -> UserOut:
    with session() as s:
        user = User(
            name=payload.name,
            language=payload.language,
            interests_text=payload.interests_text,
            telegram_chat_id=payload.telegram_chat_id,
            embedding=summarize.embed(payload.interests_text),
        )
        s.add(user)
        s.flush()
        return UserOut(id=user.id, name=user.name, language=user.language)


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
            status=d.status,
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
