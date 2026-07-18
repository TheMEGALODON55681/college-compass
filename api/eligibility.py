"""Given a student, returns eligible college-branches for the upcoming year,
banded safe/moderate/dream, using the cutoff regressor's forecast rather
than a raw prior-year lookup - this is Phase 2's "swap the direct lookup for
the trained model behind the same interface."

This filters on attainability only: rank, category, quota/home-state
resolution, and the reach margin. The preference fields on StudentProfile
(preferred branch, budget, ownership, NIRF appetite) are carried through
unused here and consumed by models/ranker.py instead, which personalizes
the ORDER of this same candidate set - eligibility decides what a student
can realistically get into, the ranker decides what to show them first.

Scope note: the regressor was trained only on Gender-Neutral seats (see
models/regressor_dataset.py's locked policy), so this serves Gender-Neutral
eligibility only. Female-only supernumerary seats are a real, smaller,
separate pool the regressor doesn't cover - a stated limitation, not a
silent omission.
"""

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
import pandas as pd

import models.cutoff_regressor as cutoff_regressor
from db.connection import get_database_url, get_engine
from models.regressor_dataset import load_regressor_training_data

SAFE_MARGIN_RATIO = 0.15
DREAM_REACH_RATIO = 0.10


@dataclass
class StudentProfile:
    """jee_rank must be on the same scale as the category's own JoSAA
    closing ranks: for OPEN it's the overall CRL rank, but for EWS/OBC-NCL/
    SC/ST it is the student's CATEGORY rank (rank among peers in that same
    category), not their overall CRL rank - that is how JoSAA itself
    publishes these categories' closing ranks, confirmed on the official
    archive page, and category ranks run on a much smaller scale than CRL
    (a category rank of 8,000 is a mid-pack OBC-NCL result, not a top-8,000
    CRL result). Feeding an overall CRL rank in for a reserved category
    would make a real student look far weaker than they are.
    """

    jee_rank: int
    category: str
    home_state: Optional[str] = None
    preferred_branch_category: Literal["cs_adjacent", "core", "any"] = "any"
    budget_annual_lakhs: Optional[float] = None
    wants_top_nirf: bool = False
    institute_ownership_pref: Literal["government", "ppp", "both"] = "both"
    prefers_home_state: bool = False


def load_reference_tables(database_url=None):
    database_url = database_url or get_database_url()
    engine = get_engine(database_url)
    colleges = pd.read_sql("SELECT * FROM colleges", engine)
    programs = pd.read_sql("SELECT * FROM programs", engine)
    reference_metadata = pd.read_sql("SELECT * FROM reference_metadata", engine)
    return colleges, programs, reference_metadata


def build_forecasts(database_url=None):
    """Loads the persisted regressor artifacts and produces a predicted
    closing rank for every real (college, program, quota, category) group.
    A serving path, not a training script - run `python -m models.cutoff_regressor`
    first if models/artifacts/ doesn't exist yet.
    """
    _, filtered = load_regressor_training_data(database_url)
    group_year = cutoff_regressor.collapse_to_one_row_per_group_year(filtered)
    nirf_df = cutoff_regressor._load_nirf(database_url)
    full_df = cutoff_regressor.build_features(group_year, nirf_df)

    delta_model, fallback_model, metadata = cutoff_regressor.load_artifacts()
    return cutoff_regressor.forecast_next_year_for_all_groups(
        full_df, delta_model, metadata["delta_features"], fallback_model, metadata["fallback_features"], alpha=metadata["alpha"]
    )


def band_for(margin_ratio, is_reach):
    if is_reach:
        return "dream"
    return "safe" if margin_ratio >= SAFE_MARGIN_RATIO else "moderate"


def merge_forecasts_with_colleges(forecasts, colleges):
    """The forecasts-to-colleges merge doesn't depend on any one student, so
    a caller producing many candidate sets in a loop (the ranker, one per
    synthetic student) should do this once and reuse it, instead of paying
    for the same merge hundreds of times - get_eligible_colleges detects an
    already-merged frame and skips redoing it.
    """
    return forecasts.merge(
        colleges[["college_id", "canonical_name", "institute_type", "state", "nirf_rank_latest"]],
        on="college_id",
        how="left",
    )


def select_best_quota_rows(candidates, student):
    """Vectorized equivalent of "for each college-branch, pick whichever
    applicable quota gives the better predicted closing rank" - no Python
    loop over groups. AI applies to every student regardless of home state.
    HS applies only where the college's own state matches the student's
    home state; otherwise OS applies - never both for the same college.
    """
    is_ai = candidates["quota"] == "AI"
    if student.home_state:
        is_hs_match = (candidates["quota"] == "HS") & (candidates["state"] == student.home_state)
        is_os_other = (candidates["quota"] == "OS") & (candidates["state"] != student.home_state)
        applicable_mask = is_ai | is_hs_match | is_os_other
    else:
        applicable_mask = is_ai | candidates["quota"].isin(["HS", "OS"])

    applicable = candidates[applicable_mask]
    if applicable.empty:
        return applicable

    best_idx = applicable.groupby(["college_id", "program_id"], sort=False)["predicted_closing_rank"].idxmin()
    return applicable.loc[best_idx]


def get_eligible_colleges(student, forecasts=None, reference_tables=None, database_url=None):
    """reference_tables lets a caller that's going to call this many times in
    a loop (the ranker, generating one candidate set per synthetic student)
    load colleges/programs/reference_metadata once instead of re-querying
    the database on every call. Passing an already-merged forecasts frame
    (see merge_forecasts_with_colleges) avoids repeating that merge too.
    """
    if forecasts is None:
        forecasts = build_forecasts(database_url)

    colleges, programs, reference_metadata = reference_tables or load_reference_tables(database_url)

    if "canonical_name" in forecasts.columns:
        merged = forecasts
    else:
        merged = merge_forecasts_with_colleges(forecasts, colleges)

    candidates = merged[merged["category"] == student.category]
    best = select_best_quota_rows(candidates, student)
    if best.empty:
        return []

    best = best.copy()
    best["margin_ratio"] = (best["predicted_closing_rank"] - student.jee_rank) / best["predicted_closing_rank"]
    is_eligible_now = student.jee_rank <= best["predicted_closing_rank"]
    is_reach = (~is_eligible_now) & (student.jee_rank <= best["predicted_closing_rank"] * (1 + DREAM_REACH_RATIO))
    best = best[is_eligible_now | is_reach].copy()
    if best.empty:
        return []
    is_reach = is_reach[best.index]

    best["band"] = np.where(is_reach, "dream", np.where(best["margin_ratio"] >= SAFE_MARGIN_RATIO, "safe", "moderate"))
    best = best.merge(programs[["program_id", "branch_name"]], on="program_id", how="left")
    best = best.merge(reference_metadata[["college_id", "fees_annual_lakhs"]], on="college_id", how="left")
    best["branch_name"] = best["branch_name"].fillna(best["program_id"])

    results = [
        {
            "college_id": row.college_id,
            "college_name": row.canonical_name,
            "institute_type": row.institute_type,
            "state": row.state,
            "nirf_rank": row.nirf_rank_latest,
            "program_id": row.program_id,
            "branch_name": row.branch_name,
            "quota_used": row.quota,
            "predicted_closing_rank": round(row.predicted_closing_rank),
            "margin": round(row.predicted_closing_rank - student.jee_rank),
            "margin_ratio": round(row.margin_ratio, 3),
            "band": row.band,
            "fees_annual_lakhs": row.fees_annual_lakhs,
            "prediction_source": row.prediction_source,
        }
        for row in best.itertuples(index=False)
    ]
    return sorted(results, key=lambda r: -r["margin_ratio"])


def _demo():
    """Concrete verification: a few real student profiles, printed with
    their bands and quota resolution, so the behavior is eyeball-checkable.
    """
    print("[eligibility] building forecasts from persisted regressor artifacts...")
    forecasts = build_forecasts()
    print(f"[eligibility] {len(forecasts)} college-branch-quota-category groups forecast for next year")

    students = [
        ("OPEN rank 5000, no home state stated", StudentProfile(jee_rank=5000, category="OPEN")),
        ("OPEN rank 5000, home state Delhi", StudentProfile(jee_rank=5000, category="OPEN", home_state="Delhi")),
        ("OBC-NCL category rank 8000, home state Uttar Pradesh", StudentProfile(jee_rank=8000, category="OBC-NCL", home_state="Uttar Pradesh")),
        ("SC category rank 3000, home state Tamil Nadu", StudentProfile(jee_rank=3000, category="SC", home_state="Tamil Nadu")),
    ]

    for label, student in students:
        results = get_eligible_colleges(student, forecasts=forecasts)
        bands = pd.Series([r["band"] for r in results]).value_counts().to_dict()
        print(f"\n=== {label} ===")
        print(f"  {len(results)} eligible college-branches: {bands}")
        most_competitive = sorted(results, key=lambda r: r["predicted_closing_rank"])[:3]
        for r in most_competitive:
            print(
                f"    [{r['band']:>8}] {r['college_name']} / {r['branch_name']} "
                f"(quota {r['quota_used']}, predicted closing {r['predicted_closing_rank']:,}, margin {r['margin']:+,})"
            )


if __name__ == "__main__":
    _demo()
