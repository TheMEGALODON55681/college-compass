"""Naive per-round closing-rank projection. Pure: no I/O, no database access,
no randomness (docs/Rules.md section 5 - this is a pattern read off history,
not a trained or validated model; Phase 6, a learned round model, is
cancelled - see docs/Phases.md).

Given a college/branch/category's already-computed final-round forecast
(models/cutoff_regressor.py's output, unmodified), scales it by a median
ratio learned per round position from 2016-2022 JoSAA rounds to produce a
per-round curve. The final round always equals the input forecast exactly,
by construction - there is nothing to fit there, the last entry copies the
input rather than looking up a ratio.

RATIO_TABLE itself lives in models/round_forecast_ratios.py, produced by
running `python -m models.build_round_ratio_table` - see that module's
header for the fit years, cell sizes, and held-out-year validation
numbers. Rerun it after any reingest that changes the cutoffs table.
"""

from models.ranker import is_cs_adjacent
from models.round_forecast_ratios import RATIO_TABLE

# docs/BuildLog.md Phase 5 Task 1: JoSAA round counts vary by year (6 in
# 2016/2020/2021/2022, 7 in 2017/2018/2019) but the two most recent years
# with round data, 2021 and 2022, agree at 6. Projected forward for the 2026
# counseling season. Refit RATIO_TABLE (python -m models.build_round_ratio_table)
# and reconsider this constant if a future reingest shows JoSAA has changed
# its round count.
PROJECTED_ROUNDS = 6


def bucket_for_round(round_number, own_final_round):
    """Fractional position in the round sequence (docs/BuildLog.md Phase 5
    Task 1), bucketed onto 1..PROJECTED_ROUNDS-1: comparing "round 6 of a
    7-round year" against "round 6 of a 6-round year" would compare
    different points in the counseling process, so the ratio is keyed on
    round / own_final_round instead of absolute round number. For a
    6-round year this maps every round onto its own bucket exactly; for a
    7-round year the middle two rounds fold into one bucket, the expected
    effect of compressing 7 positions onto a 6-round target.

    own_final_round is the series' own last round, whatever it is - a key
    that closes early (round 4 of a nominal 6-round year) or a thin/partial
    series both key correctly, since this only ever looks at round_number
    and the series' own final round, never a year-wide constant.
    round_number == own_final_round is never passed here in practice
    (project_rounds copies the final round directly, per the anchoring
    contract) but is not a caller precondition this function itself
    enforces. Shared with models/build_round_ratio_table.py, which fits
    RATIO_TABLE with this exact same bucketing - imported from here, not
    reimplemented there, so the two can never disagree on the keying.
    """
    fraction = round_number / own_final_round
    bucket = round(fraction * PROJECTED_ROUNDS)
    return min(max(bucket, 1), PROJECTED_ROUNDS - 1)


def project_rounds(final_closing_rank, category, branch_name):
    """final_closing_rank: the existing final-round forecast for this
    college/branch/category/quota (unmodified - this function only reads
    it). Returns PROJECTED_ROUNDS entries, round 1 through PROJECTED_ROUNDS,
    each {"round": int, "projected_closing_rank": int}. The last entry's
    projected_closing_rank equals final_closing_rank exactly - the round
    curve is anchored to the headline forecast by construction, not by
    rounding coincidence.

    Raises KeyError for a category outside RATIO_TABLE's fixed vocabulary
    (docs/Rules.md section 4) - callers wrap this per docs/Rules.md section
    7, the same pattern models/trend.py's caller already uses.
    """
    branch_family = "cs_adjacent" if is_cs_adjacent(branch_name) else "core"
    rounds = [
        {"round": r, "projected_closing_rank": round(final_closing_rank * RATIO_TABLE[(category, branch_family, r)])}
        for r in range(1, PROJECTED_ROUNDS)
    ]
    rounds.append({"round": PROJECTED_ROUNDS, "projected_closing_rank": final_closing_rank})
    return rounds
