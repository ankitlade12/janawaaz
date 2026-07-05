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
