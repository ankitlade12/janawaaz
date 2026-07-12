from datetime import date, datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from janawaaz.config import EMBEDDING_DIM


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    base_url: Mapped[str] = mapped_column(String(500))
    adapter: Mapped[str] = mapped_column(String(80))  # registry key, e.g. "trai"
    last_swept_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(Text)
    body_url: Mapped[str] = mapped_column(String(800))  # PDF / detail page we parsed
    body_text: Mapped[str | None] = mapped_column(Text)
    summary_en: Mapped[str | None] = mapped_column(Text)
    ministry: Mapped[str | None] = mapped_column(String(300))  # ministry / regulator / division
    deadline: Mapped[date | None] = mapped_column(Date)
    deadline_span: Mapped[str | None] = mapped_column(Text)  # verbatim evidence for the deadline
    deadline_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    comment_channel: Mapped[str | None] = mapped_column(String(800))
    published_at: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed | unknown
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(10), default="en")  # en | hi | mr | ...
    interests_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    telegram_chat_id: Mapped[str | None] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MatchLedger(Base):
    """Append-only service record for each gate evaluation behind an alert."""

    __tablename__ = "match_ledger"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "user_id", "document_fingerprint",
            name="uq_match_document_user_fingerprint",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    similarity: Mapped[float] = mapped_column(Float)
    verifier_verdict: Mapped[str | None] = mapped_column(String(20))  # yes | no | skipped
    verifier_reason: Mapped[str | None] = mapped_column(Text)
    evidence_span: Mapped[str | None] = mapped_column(Text)
    span_verified: Mapped[bool | None] = mapped_column(Boolean)
    tier: Mapped[int] = mapped_column(SmallInteger)  # 1 confirmed | 2 possible | 3 rejected
    # A content-derived idempotency key. A revised paper can be evaluated again,
    # while retries of the same paper/user decision reuse the existing row.
    document_fingerprint: Mapped[str] = mapped_column(String(64), default="unversioned")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("ledger_id", "channel", name="uq_alert_ledger_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ledger_id: Mapped[int] = mapped_column(ForeignKey("match_ledger.id"))
    channel: Mapped[str] = mapped_column(String(20), default="telegram")
    payload_translated: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="en")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | sent | failed
