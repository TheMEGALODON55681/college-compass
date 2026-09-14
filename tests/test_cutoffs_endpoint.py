"""Runnable checks for GET /cutoffs and its query layer: a real
college/program/category/quota combo from the shipped DB returns real,
year-sorted history with round and opening_rank attached, a combo that
doesn't exist returns an honest empty list, and the bulk multi-key query
agrees with the single-key query row for row - the case that matters most,
since a bulk path that quietly disagrees with the single path would be worse
than not having one.

Keys below are real rows in the shipped DB (verified directly against
college_compass.db), not invented:
- Assam University Silchar / Agricultural Engineering / OPEN / AI: 9 years,
  including 2024, whose round is null (2023-2024 have no round breakdown -
  see docs/Memory.md).
- ABV-IIITM Gwalior / the integrated IT program / OBC-NCL / AI: exactly one
  year on record.
- Assam University Silchar / Agricultural Engineering / "EWS (PwD)" / AI: a
  real college and program with zero rows for that category - never offered,
  not a lookup failure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.main import get_cutoff_history, get_cutoff_history_bulk

FULL_HISTORY_KEY = ("assam-university-silchar", "agricultural-engineering-bachelor-of-technology-4y", "OPEN", "AI")
SINGLE_YEAR_KEY = (
    "atal-bihari-vajpayee-indian-institute-of-information-technology-management-gwalior",
    "b-tech-information-technology-and-mba-m-tech-information-technology-integrated-b-tech-and-m-tech-mba-5y",
    "OBC-NCL",
    "AI",
)
NO_HISTORY_KEY = ("assam-university-silchar", "agricultural-engineering-bachelor-of-technology-4y", "EWS (PwD)", "AI")
INVALID_KEY = ("not-a-real-college", "not-a-real-program", "OPEN", "AI")


def test_known_combo_returns_sorted_history_with_round_and_opening_rank():
    history = get_cutoff_history(*FULL_HISTORY_KEY)
    assert len(history) > 0
    years = [h["year"] for h in history]
    assert years == sorted(years)
    assert len(years) == len(set(years))  # one point per year, not one per JoSAA round
    assert all(h["closing_rank"] > 0 for h in history)
    assert all("round" in h and "opening_rank" in h for h in history)


def test_single_year_key_returns_one_row():
    history = get_cutoff_history(*SINGLE_YEAR_KEY)
    assert len(history) == 1


def test_no_history_key_returns_empty_not_error():
    """Real college, real program, a category that was simply never offered
    for it - same honest empty list as an outright invalid key, not an error.
    """
    history = get_cutoff_history(*NO_HISTORY_KEY)
    assert history == []


def test_unknown_combo_returns_empty_not_error():
    history = get_cutoff_history(*INVALID_KEY)
    assert history == []


def test_null_round_passes_through_as_null():
    """2023 and 2024 carry no round breakdown at the source (see
    docs/Memory.md) - those years must come back with round: null, never a
    placeholder round number and never a dropped row.
    """
    history = get_cutoff_history(*FULL_HISTORY_KEY)
    year_2024 = next(h for h in history if h["year"] == 2024)
    assert year_2024["round"] is None
    assert year_2024["closing_rank"] > 0  # the row itself isn't dropped


def test_bulk_query_matches_single_key_path():
    keys = [FULL_HISTORY_KEY, SINGLE_YEAR_KEY, NO_HISTORY_KEY, INVALID_KEY]
    bulk_result = get_cutoff_history_bulk(keys)
    assert set(bulk_result.keys()) == set(keys)
    for key in keys:
        assert bulk_result[key] == get_cutoff_history(*key), key


def test_bulk_query_handles_empty_input():
    assert get_cutoff_history_bulk([]) == {}


if __name__ == "__main__":
    test_known_combo_returns_sorted_history_with_round_and_opening_rank()
    test_single_year_key_returns_one_row()
    test_no_history_key_returns_empty_not_error()
    test_unknown_combo_returns_empty_not_error()
    test_null_round_passes_through_as_null()
    test_bulk_query_matches_single_key_path()
    test_bulk_query_handles_empty_input()
    print("ok")
