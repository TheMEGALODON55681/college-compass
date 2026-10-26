"""A question with no student profile reads actual closing ranks straight from
the cutoffs table. The product serves Gender-Neutral seats only, so a
Female-only row must never reach the bundle, and a college whose latest year
carries one row per counselling round must attach the final round only, not
every round under the same label. Each expected set comes from its own SQL
against the real database, not from the function under test.
"""

import sys
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.eligibility import load_reference_tables
from db.connection import get_database_url, get_engine
from models.counsellor_retrieval import _historical_closing_ranks, build_context_bundle, build_lookup_cache

IIT_DELHI = "indian-institute-of-technology-delhi"
# Its latest Gender-Neutral year in quota AI is older than 2024 and has up to six rounds.
PONDICHERRY = "pondicherry-engineering-college-puducherry"
GENDER_NEUTRAL = "Gender-Neutral"
FEMALE_ONLY = "Female-only (including Supernumerary)"


def _rows(sql, **params):
    with get_engine(get_database_url()).connect() as conn:
        return conn.execute(text(sql), params).fetchall()


def _latest_year(college_id, quota):
    return _rows(
        "SELECT MAX(year) FROM cutoffs WHERE college_id = :c AND quota = :q AND gender_seat_type = :p",
        c=college_id,
        q=quota,
        p=GENDER_NEUTRAL,
    )[0][0]


def _closing_ranks(college_id, quota, year, pool):
    rows = _rows(
        "SELECT closing_rank FROM cutoffs WHERE college_id = :c AND quota = :q AND year = :y AND gender_seat_type = :p",
        c=college_id,
        q=quota,
        y=year,
        p=pool,
    )
    return Counter(r[0] for r in rows)


@pytest.fixture(scope="module")
def state():
    return {"counsellor_lookup": build_lookup_cache(), "reference_tables": load_reference_tables()}


def test_history_for_iit_delhi_holds_gender_neutral_rows_only():
    year = _latest_year(IIT_DELHI, "AI")
    assert _closing_ranks(IIT_DELHI, "AI", year, FEMALE_ONLY), "no Female-only rows to leak: the test would prove nothing"

    records = _historical_closing_ranks(IIT_DELHI, None, False)

    assert Counter(r["value"] for r in records) == _closing_ranks(IIT_DELHI, "AI", year, GENDER_NEUTRAL)


def test_no_profile_bundle_quotes_only_gender_neutral_ranks(state):
    year = _latest_year(IIT_DELHI, "AI")

    bundle = build_context_bundle("closing ranks for IIT Delhi", None, state)

    quoted = Counter(r["value"] for r in bundle["records"] if r["field"] == "actual_closing_rank")
    assert quoted == _closing_ranks(IIT_DELHI, "AI", year, GENDER_NEUTRAL)


def test_cutoff_history_readers_serve_gender_neutral_seats_only():
    """The audit of the other cutoff readers found no leak: /cutoffs and the
    bulk trend lookup exclude Female-only rows. This pins it, so the counsellor
    and the chart cannot drift apart on which seat pool a rank belongs to.
    """
    from api.main import get_cutoff_history_bulk

    year = _latest_year(IIT_DELHI, "AI")
    keys = [
        (IIT_DELHI, r[0], r[1], "AI")
        for r in _rows("SELECT DISTINCT program_id, category FROM cutoffs WHERE college_id = :c AND quota = 'AI'", c=IIT_DELHI)
    ]

    history = get_cutoff_history_bulk(keys)

    latest = Counter(point["closing_rank"] for points in history.values() for point in points if point["year"] == year)
    assert latest == _closing_ranks(IIT_DELHI, "AI", year, GENDER_NEUTRAL)


def test_history_of_a_college_with_rounds_keeps_the_final_round_only():
    year = _latest_year(PONDICHERRY, "AI")
    rounds = _rows(
        "SELECT COUNT(DISTINCT round) FROM cutoffs WHERE college_id = :c AND quota = 'AI' AND year = :y AND gender_seat_type = :p",
        c=PONDICHERRY,
        y=year,
        p=GENDER_NEUTRAL,
    )[0][0]
    assert rounds > 1, "no per-round rows: the test would prove nothing"
    final_round = _rows(
        """
        SELECT cu.closing_rank FROM cutoffs cu
        WHERE cu.college_id = :c AND cu.quota = 'AI' AND cu.year = :y AND cu.gender_seat_type = :p
          AND cu.round = (SELECT MAX(x.round) FROM cutoffs x
                          WHERE x.college_id = cu.college_id AND x.program_id = cu.program_id AND x.category = cu.category
                            AND x.quota = cu.quota AND x.year = cu.year AND x.gender_seat_type = cu.gender_seat_type)
        """,
        c=PONDICHERRY,
        y=year,
        p=GENDER_NEUTRAL,
    )

    records = _historical_closing_ranks(PONDICHERRY, None, False)

    assert Counter(r["value"] for r in records) == Counter(r[0] for r in final_round)
