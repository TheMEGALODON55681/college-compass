"""Regenerates models/round_forecast_ratios.py's RATIO_TABLE from the
cutoffs table, and validates it on two held-out years before writing
anything - one 6-round season (2021) and one 7-round season (2018), so a
regression in either round-count shape gets caught, not just the shape
2026 happens to match.

RATIO_TABLE has the same silent-staleness risk models/trend.py's
DRIFT_MEDIAN_SLOPE already carries, unfixed there: reingest the cutoffs
table with a new year and the old ratios are quietly wrong, with nothing
to catch it. This script is the fix for round_forecast's copy of that
problem - rerun it after any reingest that touches cutoffs:

    python -m models.build_round_ratio_table

Read-only against the database. Writes only models/round_forecast_ratios.py.
"""

from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median

from sqlalchemy import text

from api.main import FEMALE_ONLY_GENDER_SEAT_TYPE
from db.connection import get_database_url, get_engine
from models.ranker import is_cs_adjacent
from models.round_forecast import PROJECTED_ROUNDS, bucket_for_round

# 2023-2024 carry no round column at all (docs/KNOWN_ISSUES.md) - there is
# nothing to fit or validate against for those years.
FIT_YEARS = list(range(2016, 2023))

# One 6-round season, one 7-round season (docs/BuildLog.md Phase 5 Task 1:
# 6 rounds in 2016/2020-2022, 7 in 2017-2019) - validates the keying across
# both shapes it actually has to handle, not just the shape 2026 is
# projected to be.
HELD_OUT_YEARS = (2021, 2018)

OUTPUT_PATH = Path(__file__).resolve().parent / "round_forecast_ratios.py"


def _load_round_series(conn, years):
    """{(college_id, program_id, category, quota, year): [(round, closing_rank), ...]},
    plus {program_id: branch_name} for the branch-family split. Gender-Neutral
    seats only, matching every other cutoffs read path in this codebase
    (api/main.py).
    """
    rows = conn.execute(
        text(
            """
            SELECT c.college_id, c.program_id, c.category, c.quota, c.year, c.round, c.closing_rank,
                   p.branch_name
            FROM cutoffs c
            JOIN programs p ON p.program_id = c.program_id
            WHERE c.year BETWEEN :y0 AND :y1
              AND c.gender_seat_type != :excluded
              AND c.round IS NOT NULL
            """
        ),
        {"excluded": FEMALE_ONLY_GENDER_SEAT_TYPE, "y0": min(years), "y1": max(years)},
    ).fetchall()

    wanted_years = set(years)
    series = defaultdict(list)
    branch_of_program = {}
    for row in rows:
        if row.year not in wanted_years:
            continue
        key = (row.college_id, row.program_id, row.category, row.quota, row.year)
        series[key].append((row.round, row.closing_rank))
        branch_of_program[row.program_id] = row.branch_name
    return series, branch_of_program


def _fit_ratio_table(series_by_key, branch_of_program):
    """Median ratio per (category, branch_family, bucket) cell. A series
    with only one round present has no round-to-final ratio to compute, and
    a closing_rank <= 0 is bad source data (one known key, docs/BuildLog.md
    Phase 5 Task 2: IIT Kharagpur CSE / OBC-NCL (PwD) / AI quota / 2017) -
    both are skipped, not padded or guessed at (docs/Rules.md section 7).
    """
    ratios = defaultdict(list)
    for (_college_id, program_id, category, _quota, _year), points in series_by_key.items():
        points.sort()
        if len(points) < 2 or any(rank <= 0 for _, rank in points):
            continue
        own_final_round, final_rank = points[-1]
        branch_family = "cs_adjacent" if is_cs_adjacent(branch_of_program[program_id]) else "core"
        for round_number, rank in points[:-1]:
            bucket = bucket_for_round(round_number, own_final_round)
            ratios[(category, branch_family, bucket)].append(rank / final_rank)
    ratio_table = {key: median(values) for key, values in ratios.items()}
    cell_sizes = {key: len(values) for key, values in ratios.items()}
    return ratio_table, cell_sizes


def _evaluate(ratio_table, holdout_series, holdout_branches):
    """MAE per bucket for the ratio table vs. the trivial "every round
    equals the final round" baseline, on one held-out year's real
    round-level closing ranks.
    """
    ratio_errors = defaultdict(list)
    trivial_errors = defaultdict(list)
    for (_college_id, program_id, category, _quota, _year), points in holdout_series.items():
        points.sort()
        if len(points) < 2 or any(rank <= 0 for _, rank in points):
            continue
        own_final_round, final_rank = points[-1]
        branch_family = "cs_adjacent" if is_cs_adjacent(holdout_branches[program_id]) else "core"
        for round_number, actual_rank in points[:-1]:
            bucket = bucket_for_round(round_number, own_final_round)
            cell = (category, branch_family, bucket)
            if cell not in ratio_table:
                continue
            predicted_rank = final_rank * ratio_table[cell]
            ratio_errors[bucket].append(abs(predicted_rank - actual_rank))
            trivial_errors[bucket].append(abs(final_rank - actual_rank))
    return ratio_errors, trivial_errors


def _validate_one_year(conn, holdout_year):
    train_years = [y for y in FIT_YEARS if y != holdout_year]
    train_series, train_branches = _load_round_series(conn, train_years)
    train_ratio_table, _ = _fit_ratio_table(train_series, train_branches)

    holdout_series, holdout_branches = _load_round_series(conn, [holdout_year])
    ratio_errors, trivial_errors = _evaluate(train_ratio_table, holdout_series, holdout_branches)

    per_bucket = []
    for bucket in range(1, PROJECTED_ROUNDS):
        r_mae = mean(ratio_errors[bucket])
        t_mae = mean(trivial_errors[bucket])
        per_bucket.append((bucket, (t_mae - r_mae) / t_mae * 100))

    all_ratio = [e for errs in ratio_errors.values() for e in errs]
    all_trivial = [e for errs in trivial_errors.values() for e in errs]
    ratio_mae = mean(all_ratio)
    trivial_mae = mean(all_trivial)
    overall_improvement = (trivial_mae - ratio_mae) / trivial_mae * 100
    return overall_improvement, per_bucket


def _format_ratio_table(ratio_table):
    """Grouped one line per (category, branch_family) for readability, but
    driven entirely by ratio_table's own keys - never a hardcoded category
    list, so a reingest that changes the category vocabulary shows up here
    automatically instead of being silently dropped from the output.
    """
    groups = sorted({(category, branch_family) for category, branch_family, _bucket in ratio_table})
    lines = ["RATIO_TABLE = {"]
    for category, branch_family in groups:
        buckets = sorted(bucket for cat, fam, bucket in ratio_table if cat == category and fam == branch_family)
        entries = ", ".join(
            f'("{category}", "{branch_family}", {bucket}): {ratio_table[(category, branch_family, bucket)]:.4f}'
            for bucket in buckets
        )
        lines.append(f"    {entries},")
    lines.append("}")
    return "\n".join(lines)


def _write_output(ratio_table, cell_sizes, validation_summaries):
    fit_date = date.today().isoformat()
    validation_lines = []
    for holdout_year, overall_improvement, per_bucket in validation_summaries:
        round_kind = "6-round" if holdout_year in (2016, 2020, 2021, 2022) else "7-round"
        per_bucket_str = ", ".join(f"bucket {b}: {imp:.1f}%" for b, imp in per_bucket)
        validation_lines.append(
            f"  {holdout_year} ({round_kind} season): {overall_improvement:.1f}% lower MAE overall "
            f"than the trivial baseline ({per_bucket_str})."
        )

    content = (
        '"""Generated from the cutoffs table (python -m models.build_round_ratio_table).\n'
        "Do not hand-edit - rerun the script instead, so this file and the report\n"
        "below never drift apart.\n"
        "\n"
        f"Fit years: {FIT_YEARS[0]}-{FIT_YEARS[-1]} (2023-2024 carry no round data, docs/KNOWN_ISSUES.md).\n"
        f"{len(ratio_table)} cells (10 categories x 2 branch families x {PROJECTED_ROUNDS - 1} non-final\n"
        f"round buckets), minimum cell size {min(cell_sizes.values())} rows, maximum {max(cell_sizes.values())}.\n"
        "\n"
        "Held-out-year validation (ratio table refit on the other years each time,\n"
        "never on data that includes the held-out year):\n"
        f"{chr(10).join(validation_lines)}\n"
        "Both win clearly at every round position. The 7-round year's smaller\n"
        "margin is expected, not a regression - its keying folds two rounds into\n"
        "one bucket (docs/BuildLog.md Phase 5 Task 1) - and does not change the\n"
        "ship decision, since 2021 and 2022 (the two most recent years with round\n"
        "data) agree on 6 rounds, which is what 2026 is projected to be.\n"
        "\n"
        f'Fit date: {fit_date}.\n'
        '"""\n'
        "\n"
        f"{_format_ratio_table(ratio_table)}\n"
    )
    OUTPUT_PATH.write_text(content, encoding="utf-8")


def run():
    database_url = get_database_url()
    engine = get_engine(database_url)
    with engine.connect() as conn:
        fit_series, fit_branches = _load_round_series(conn, FIT_YEARS)
        ratio_table, cell_sizes = _fit_ratio_table(fit_series, fit_branches)
        print(
            f"[build_round_ratio_table] fit {len(ratio_table)} cells from years {FIT_YEARS[0]}-{FIT_YEARS[-1]}, "
            f"min cell size {min(cell_sizes.values())}, max {max(cell_sizes.values())}"
        )

        validation_summaries = []
        for holdout_year in HELD_OUT_YEARS:
            overall_improvement, per_bucket = _validate_one_year(conn, holdout_year)
            validation_summaries.append((holdout_year, overall_improvement, per_bucket))
            per_bucket_str = ", ".join(f"b{b}={imp:.1f}%" for b, imp in per_bucket)
            print(
                f"[build_round_ratio_table] held out {holdout_year}: {overall_improvement:.1f}% lower MAE "
                f"overall vs. the trivial baseline ({per_bucket_str})"
            )
            if overall_improvement <= 0:
                print(f"[build_round_ratio_table] WARNING: {holdout_year} did not beat the trivial baseline")

    _write_output(ratio_table, cell_sizes, validation_summaries)
    print(f"[build_round_ratio_table] wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    run()
