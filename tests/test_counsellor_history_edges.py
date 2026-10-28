"""Cases the history attached to a named college must survive: the 90-row cap
ordering by the student's category, a college with no history, and a phrasing
that merely contains "like". Each expected value comes from SQL against the real
database.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import get_database_url, get_engine
from models.counsellor_retrieval import (
    SHARED_HISTORY_ROW_CAP,
    _historical_closing_ranks,
    _wants_semantic,
    build_context_bundle,
)
from test_counsellor_out_of_reach import PARTLY_IN_REACH, _actual_ranks, _gender_neutral_cse_ranks, _state

IIT_PATNA = "indian-institute-of-technology-patna"
ISM_DHANBAD = "indian-school-of-mines-dhanbad"
CSE = "Computer Science and Engineering"


def _patna_cse_rank(category):
    sql = text(
        """
        SELECT cu.closing_rank FROM cutoffs cu JOIN programs p ON cu.program_id = p.program_id
        WHERE cu.college_id = :c AND cu.quota = 'AI' AND cu.gender_seat_type = 'Gender-Neutral'
          AND p.branch_name = :b AND cu.category = :cat AND cu.round IS NULL
          AND cu.year = (SELECT MAX(year) FROM cutoffs WHERE college_id = :c AND quota = 'AI' AND gender_seat_type = 'Gender-Neutral')
        """
    )
    with get_engine(get_database_url()).connect() as conn:
        return [r[0] for r in conn.execute(sql, {"c": IIT_PATNA, "b": CSE, "cat": category})]


@pytest.mark.parametrize("category", ["EWS", "OBC-NCL", "SC", "ST"])
def test_cap_keeps_the_students_own_category_rows(category):
    """IIT Patna has 149 history rows and the cap keeps 90. "CSE" is not read as a
    branch, so no branch filter narrows the rows first. The student's category
    must outrank the alphabetical order of the branches, or a reserved-category
    student loses the very row they asked for.
    """
    expected = _patna_cse_rank(category)
    assert expected, "no Computer Science row for this category: the test would prove nothing"

    bundle = build_context_bundle("What is the closing rank for CSE at IIT Patna?", {"jee_rank": 90000, "category": category}, _state())

    rows = [r for r in bundle["records"] if r["field"] == "actual_closing_rank" and r["branch"] == CSE]
    assert {(r["category"], r["value"]) for r in rows} >= {(category, v) for v in expected}
    assert any(r["category"] == "OPEN" for r in rows)
    assert len([r for r in bundle["records"] if r["field"] == "actual_closing_rank"]) <= SHARED_HISTORY_ROW_CAP


@pytest.mark.parametrize("cs_adjacent_only", [False, True])
@pytest.mark.parametrize("cap", [None, SHARED_HISTORY_ROW_CAP])
def test_college_without_history_gives_no_rows_instead_of_an_error(cap, cs_adjacent_only):
    """Four colleges have only pre-2018 data, so no Gender-Neutral row. The
    branch filters and the cap's sort used to fail on the empty frame, and a
    student's software question about one of them answered HTTP 500.
    """
    assert _historical_closing_ranks(ISM_DHANBAD, None, cs_adjacent_only, max_rows=cap) == []


def test_software_question_about_a_college_without_history_builds_a_bundle():
    bundle = build_context_bundle(
        "closing rank for software at Indian School of Mines Dhanbad", {"jee_rank": 5000, "category": "OPEN"}, _state()
    )

    assert not [r for r in bundle["records"] if r["field"] == "actual_closing_rank"]


def test_polite_phrasing_is_not_a_request_for_alternatives():
    assert not _wants_semantic("I'd like to know the closing rank for CSE at IIT Delhi")
    assert not _wants_semantic("I’d like the closing rank for CSE at IIT Delhi")
    assert not _wants_semantic("I would like to know the closing rank for CSE at IIT Delhi")
    assert _wants_semantic("colleges like IIT Delhi")


def test_polite_phrasing_still_gets_the_history_of_the_named_college():
    bundle = build_context_bundle("I'd like to know the closing rank for CSE at IIT Delhi", PARTLY_IN_REACH, _state())

    assert bundle["mode"] == "structured"
    assert not _gender_neutral_cse_ranks() - _actual_ranks(bundle)
