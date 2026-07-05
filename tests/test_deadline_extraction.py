from datetime import date

from janawaaz.pipeline.extract import extract_deadline

# Phrasings modeled on real TRAI/ministry consultation papers.

def test_numeric_date_with_on_or_before():
    text = (
        "Stakeholders are requested to furnish their written comments on the "
        "consultation paper on or before 21/08/2026 to the Advisor (B&CS)."
    )
    r = extract_deadline(text)
    assert r.deadline == date(2026, 8, 21)
    assert r.verified and r.span and "21/08/2026" in r.span


def test_day_month_name_format():
    text = (
        "Comments on the draft regulation may be submitted by 15th September, 2026 "
        "through the e-consultation module."
    )
    r = extract_deadline(text)
    assert r.deadline == date(2026, 9, 15)
    assert r.verified


def test_comments_preferred_over_counter_comments():
    text = (
        "Written comments on the Consultation Paper are invited from stakeholders "
        "by 20.07.2026. Counter comments, if any, may be submitted by 03.08.2026."
    )
    r = extract_deadline(text)
    assert r.deadline == date(2026, 7, 20)


def test_last_date_phrasing():
    text = "The last date for submission of suggestions is 5 August 2026."
    r = extract_deadline(text)
    assert r.deadline == date(2026, 8, 5)


def test_no_deadline_returns_none():
    text = (
        "This paper discusses spectrum allocation methodology in detail and the "
        "history of licensing in India since 1994."
    )
    r = extract_deadline(text)
    assert r.deadline is None and r.method == "none" and not r.verified


def test_date_without_comment_context_ignored():
    text = "The Authority released its previous tariff order dated 14/03/2026 covering DTH."
    r = extract_deadline(text)
    assert r.deadline is None


def test_dotted_numeric_dd_mm_yyyy():
    text = "Comments may be sent latest by 30.09.2026 to the undersigned."
    r = extract_deadline(text)
    assert r.deadline == date(2026, 9, 30)


def test_historical_reference_rejected_with_published_after():
    # Real failure seen on TRAI CP_30042026.pdf: the paper cites a 2023
    # consultation's comment window; that date must not become the deadline.
    text = (
        "In the earlier consultation, comments were invited by 20.01.2023 from "
        "all stakeholders. Stakeholders may now submit comments on the present "
        "paper on or before 28/05/2026."
    )
    r = extract_deadline(text, published_after=date(2026, 4, 30))
    assert r.deadline == date(2026, 5, 28)

    r_all_old = extract_deadline(
        "Comments were invited by 20.01.2023 from stakeholders.",
        published_after=date(2026, 4, 30),
    )
    assert r_all_old.deadline is None
