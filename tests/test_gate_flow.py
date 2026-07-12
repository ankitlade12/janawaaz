"""The gate, end to end against a real database, with the LLM verifier mocked.

Covers the three verdicts that define the product:
  - verified span        -> Tier 1 (push)
  - unverifiable span    -> Tier 2 (audit review only) — the false-positive killer
  - verifier says no     -> Tier 3 (ledger only)
and alert composition (deadline honesty + cited span).
"""

import pytest

from janawaaz.models import Document, User
from janawaaz.pipeline import matching, notify
from janawaaz.pipeline.matching import Verdict
from janawaaz.pipeline.summarize import _dev_embedding

DOC_TEXT = (
    "The proposed tariff amendment revises ceiling prices for rural broadband "
    "subscribers. Stakeholders may submit comments on or before 21/08/2026."
)


@pytest.fixture()
def doc_and_user(db_session):
    doc = Document(
        source_id=_source_id(db_session),
        external_id="test-gate-doc",
        title="Test Consultation on Rural Broadband Tariffs",
        body_url="https://example.gov.in/paper.pdf",
        body_text=DOC_TEXT,
        summary_en="Revises rural broadband price ceilings.",
        embedding=_dev_embedding("rural broadband tariff ceiling"),
    )
    user = User(
        name="Gate Test User",
        language="mr",
        interests_text="rural broadband connectivity and tariffs",
        embedding=_dev_embedding("rural broadband connectivity and tariffs"),
    )
    db_session.add_all([doc, user])
    db_session.flush()
    return doc, user


def _source_id(s) -> int:
    from janawaaz.pipeline.runner import upsert_source

    return upsert_source(s, "trai").id


def test_verified_yes_promotes_to_tier1(db_session, doc_and_user, monkeypatch):
    doc, user = doc_and_user
    monkeypatch.setattr(
        matching, "verify_match",
        lambda *a, **k: Verdict("yes", "affects rural subscribers", "rural broadband subscribers", True),
    )
    row = matching.gate_match(db_session, doc, user, similarity=0.55)
    assert row.tier == 1 and row.span_verified


def test_unverifiable_span_demotes_to_tier2(db_session, doc_and_user, monkeypatch):
    doc, user = doc_and_user
    monkeypatch.setattr(
        matching, "verify_match",
        lambda *a, **k: Verdict("yes", "sounds relevant", "village internet users", False),
    )
    row = matching.gate_match(db_session, doc, user, similarity=0.55)
    assert row.tier == 2  # yes without verifiable evidence can never push


def test_verifier_no_rejects_to_tier3(db_session, doc_and_user, monkeypatch):
    doc, user = doc_and_user
    monkeypatch.setattr(
        matching, "verify_match",
        lambda *a, **k: Verdict("no", "telecom paper, unrelated profile", None, False),
    )
    row = matching.gate_match(db_session, doc, user, similarity=0.55)
    assert row.tier == 3


def test_below_threshold_never_calls_verifier(db_session, doc_and_user, monkeypatch):
    doc, user = doc_and_user

    def boom(*a, **k):
        raise AssertionError("verifier must not run below threshold")

    monkeypatch.setattr(matching, "verify_match", boom)
    row = matching.gate_match(db_session, doc, user, similarity=0.05)
    assert row.tier == 3 and row.verifier_verdict == "skipped"


def test_alert_text_carries_span_and_deadline_honesty(db_session, doc_and_user, monkeypatch):
    from datetime import date

    doc, user = doc_and_user
    monkeypatch.setattr(
        matching, "verify_match",
        lambda *a, **k: Verdict("yes", "ok", "rural broadband subscribers", True),
    )
    row = matching.gate_match(db_session, doc, user, similarity=0.55)

    doc.deadline = date(2026, 8, 21)
    doc.deadline_verified = True
    text = notify.build_alert_text(doc, row)
    assert "rural broadband subscribers" in text
    assert "21 Aug 2026" in text

    doc.deadline_verified = False
    text2 = notify.build_alert_text(doc, row)
    assert "unverified" in text2


def test_gate_and_alert_are_idempotent(db_session, doc_and_user, monkeypatch):
    doc, user = doc_and_user
    monkeypatch.setattr(
        matching, "verify_match",
        lambda *a, **k: Verdict("yes", "ok", "rural broadband subscribers", True),
    )
    first = matching.gate_match(db_session, doc, user, similarity=0.55)
    second = matching.gate_match(db_session, doc, user, similarity=0.55)
    assert first.id == second.id

    alert_one = notify.send_alert(db_session, doc, user, first)
    alert_two = notify.send_alert(db_session, doc, user, second)
    assert alert_one.id == alert_two.id
