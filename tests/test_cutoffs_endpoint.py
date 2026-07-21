"""One runnable check for GET /cutoffs: a real college/program/category/quota
combo from the shipped DB returns real, year-sorted history, and a combo that
doesn't exist returns an honest empty list, never an error or invented data.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.main import get_cutoff_history


def test_known_combo_returns_sorted_history():
    history = get_cutoff_history(
        "indian-institute-of-technology-bhubaneswar",
        "civil-engineering-bachelor-of-technology-4y",
        "OPEN",
        "AI",
    )
    assert len(history) > 0
    years = [h["year"] for h in history]
    assert years == sorted(years)
    assert len(years) == len(set(years))  # one point per year, not one per JoSAA round
    assert all(h["closing_rank"] > 0 for h in history)


def test_unknown_combo_returns_empty_not_error():
    history = get_cutoff_history("not-a-real-college", "not-a-real-program", "OPEN", "AI")
    assert history == []


if __name__ == "__main__":
    test_known_combo_returns_sorted_history()
    test_unknown_combo_returns_empty_not_error()
    print("ok")
