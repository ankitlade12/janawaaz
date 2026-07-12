from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from janawaaz.config import settings

_engine = None
_SessionLocal = None


def _normalize_url(url: str) -> str:
    # Render/Heroku-style URLs say postgres:// or postgresql://, which SQLAlchemy
    # routes to psycopg2; we ship psycopg v3.
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(_normalize_url(settings().database_url), pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


@contextmanager
def session() -> Iterator[Session]:
    engine()
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def init_db() -> None:
    """Create the pgvector extension and all tables. Idempotent."""
    from janawaaz import models  # noqa: F401 — register mappings

    with engine().connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    models.Base.metadata.create_all(engine())
    # create_all does not alter an existing hackathon database. Keep these
    # additive migrations here so the deployed demo upgrades without Alembic.
    with engine().begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE"))
        conn.execute(text(
            "ALTER TABLE match_ledger ADD COLUMN IF NOT EXISTS "
            "document_fingerprint VARCHAR(64) DEFAULT 'unversioned'"
        ))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_match_live_fingerprint
            ON match_ledger (document_id, user_id, document_fingerprint)
            WHERE document_fingerprint <> 'unversioned'
        """))
        # Repair data already ingested from government anti-bot challenge pages.
        conn.execute(text("""
            UPDATE documents
               SET summary_en = NULL, body_text = NULL, embedding = NULL
             WHERE lower(coalesce(summary_en, '')) LIKE '%captcha%'
                OR lower(coalesce(summary_en, '')) LIKE '%security check%'
                OR lower(coalesce(summary_en, '')) LIKE '%enable javascript%'
        """))
        conn.execute(text("""
            UPDATE documents
               SET status = 'closed'
             WHERE deadline IS NOT NULL AND deadline < CURRENT_DATE
        """))
