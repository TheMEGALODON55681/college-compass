"""Runnable checks for models/round_forecast.py's naive per-round projection.

Every bucket value asserted below was confirmed by actually running
bucket_for_round (docs/BuildLog.md Phase 5 Task 1), not hand-computed -
Python's round() uses banker's rounding, which does not always match naive
rounding at the .5 boundary these fractions produce.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models.round_forecast as round_forecast
from models.round_forecast import PROJECTED_ROUNDS, RATIO_TABLE, bucket_for_round, project_rounds


def test_bucketing_complete_six_round_series():
    """A key with a complete round series in a 6-round year: fractional
    position keying should map each round onto its own bucket exactly, with
    no compression, since PROJECTED_ROUNDS itself is 6.
    """
    assert [bucket_for_round(r, 6) for r in range(1, 6)] == [1, 2, 3, 4, 5]


def test_bucketing_partial_round_series():
    """A key that closed early - round data only exists for rounds 1-4 of
    what a full season would carry, not because rows are missing but
    because that program's own last round was 4 (some branches fill and
    stop appearing in later rounds). bucket_for_round only ever looks at
    round_number and the series' own final round, so a thin series keys
    correctly without needing to know the year-wide round count at all.
    """
    assert [bucket_for_round(r, 4) for r in range(1, 4)] == [2, 3, 4]


def test_bucketing_handles_six_and_seven_round_years():
    """A key from a 6-round year and a key from a 7-round year (docs/
    BuildLog.md Phase 5 Task 1: counts genuinely vary, 6 in 2016/2020-2022,
    7 in 2017-2019). Both must key into the same 1..PROJECTED_ROUNDS-1 range
    with no collision at the boundary - a 7-round year's middle two rounds
    (3 and 4) intentionally fold into one bucket (3), which is the expected
    effect of compressing 7 positions onto a 6-round target, not a bug.
    """
    six_round_year = [bucket_for_round(r, 6) for r in range(1, 6)]
    seven_round_year = [bucket_for_round(r, 7) for r in range(1, 7)]
    assert six_round_year == [1, 2, 3, 4, 5]
    assert seven_round_year == [1, 2, 3, 3, 4, 5]
    assert all(1 <= b <= PROJECTED_ROUNDS - 1 for b in six_round_year + seven_round_year)


def test_anchoring_final_round_equals_headline_forecast():
    """The consistency check docs/Phases.md's Phase 5 section names directly:
    the final-round projection must equal the input forecast exactly, for
    every category and both branch families - not approximately, since the
    last entry copies the input rather than multiplying by a ratio.

    Loops over all ten real categories (docs/Rules.md section 4's fixed
    vocabulary), not a sample of them, so a generation bug that silently
    truncates RATIO_TABLE (models/round_forecast_ratios.py, rebuilt by
    running models/build_round_ratio_table.py) shows up here as a KeyError
    rather than passing on an untested category.
    """
    real_categories = (
        "OPEN", "OPEN (PwD)", "OBC-NCL", "OBC-NCL (PwD)", "EWS", "EWS (PwD)",
        "SC", "SC (PwD)", "ST", "ST (PwD)",
    )
    for category in real_categories:
        for branch_name in ("Computer Science and Engineering", "Mechanical Engineering"):
            result = project_rounds(12345, category, branch_name)
            assert result[-1] == {"round": PROJECTED_ROUNDS, "projected_closing_rank": 12345}
            assert len(result) == PROJECTED_ROUNDS
            assert [r["round"] for r in result] == list(range(1, PROJECTED_ROUNDS + 1))


def test_monotonicity_is_not_assumed():
    """project_rounds is a straight lookup-and-multiply over RATIO_TABLE - it
    must not sort, clamp, or smooth the curve into a particular direction.
    Every real RATIO_TABLE cell happens to be non-decreasing (docs/
    BuildLog.md: cutoffs empirically loosen round over round), so this
    injects a synthetic cell where round 3 tightens back below round 2 and
    confirms the output reflects that dip rather than forcing an increase.
    """
    fake_category = "__test_only_non_monotonic__"
    branch_family = "core"
    injected = {
        (fake_category, branch_family, 1): 0.80,
        (fake_category, branch_family, 2): 0.95,
        (fake_category, branch_family, 3): 0.85,
        (fake_category, branch_family, 4): 0.90,
        (fake_category, branch_family, 5): 0.92,
    }
    RATIO_TABLE.update(injected)
    try:
        result = project_rounds(10000, fake_category, "Mechanical Engineering")
        ranks = [r["projected_closing_rank"] for r in result]
        assert ranks[1] > ranks[2]  # round 2 projects looser than round 3 - a real dip, not smoothed away
    finally:
        for key in injected:
            del RATIO_TABLE[key]


def test_unknown_category_raises():
    """RATIO_TABLE's category vocabulary is fixed (docs/Rules.md section 4).
    An unrecognized category raises rather than silently guessing - the
    caller wraps this per docs/Rules.md section 7, the same pattern
    models/trend.py's caller already uses for the trend field.
    """
    try:
        project_rounds(10000, "not-a-real-category", "Computer Science and Engineering")
        assert False, "expected a KeyError"
    except KeyError:
        pass


if __name__ == "__main__":
    test_bucketing_complete_six_round_series()
    test_bucketing_partial_round_series()
    test_bucketing_handles_six_and_seven_round_years()
    test_anchoring_final_round_equals_headline_forecast()
    test_monotonicity_is_not_assumed()
    test_unknown_category_raises()
    print("ok")
