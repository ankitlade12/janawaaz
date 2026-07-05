"""Shared fixtures.

DB-backed tests run against whatever DATABASE_URL points at (docker-compose
locally, a pgvector service container in CI) and are skipped cleanly when no
database is reachable, so the pure-unit suite still passes anywhere.
"""

import pytest


@pytest.fixture(scope="session")
def db():
    from sqlalchemy import text

    from janawaaz.db import engine, init_db

    try:
        with engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("no database reachable; skipping DB-backed tests")
    init_db()
    return engine()


@pytest.fixture()
def db_session(db):
    from janawaaz.db import session

    with session() as s:
        yield s
        s.rollback()  # tests never persist
