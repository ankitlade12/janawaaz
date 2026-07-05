"""JanAwaaz web service.

POST /users           — onboarding: free-text interests -> embedded profile
GET  /feed            — public feed of consultations with deadlines (standalone useful,
                        and the fallback demo if notification plumbing breaks)
GET  /ledger/{id}     — provenance: why an alert fired, score, verdict, cited span
GET  /healthz
"""

from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from janawaaz.db import init_db, session
from janawaaz.models import Document, MatchLedger, Source, User
from janawaaz.pipeline import summarize
from janawaaz.pipeline.notify import days_remaining

app = FastAPI(title="JanAwaaz", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()


class UserIn(BaseModel):
    name: str = Field(..., max_length=200)
    language: str = Field("en", pattern="^(en|hi|mr)$")
    interests_text: str = Field(..., min_length=10, max_length=2000)
    telegram_chat_id: str | None = None


class UserOut(BaseModel):
    id: int
    name: str
    language: str


@app.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserIn) -> UserOut:
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


@app.get("/feed", response_model=list[FeedItem])
def feed(limit: int = 50) -> list[FeedItem]:
    with session() as s:
        rows = s.execute(
            select(Document, Source.name)
            .join(Source, Document.source_id == Source.id)
            .order_by(Document.published_at.desc().nulls_last())
            .limit(min(limit, 200))
        ).all()
        return [
            FeedItem(
                id=d.id,
                source=src_name,
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
            for d, src_name in rows
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


@app.get("/ledger/{ledger_id}", response_model=LedgerOut)
def ledger(ledger_id: int) -> LedgerOut:
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
