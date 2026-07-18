"""The migration's required gate: runs the same representative inputs
through the real application code against SQLite and against Postgres, and
asserts the outputs are identical. If anything differs, this raises and the
migration is not done - this script never loosens an assertion to pass.

Covers:
- /recommend for a handful of rank/category/home-state combinations,
  including a reserved-category-plus-home-state case (OBC-NCL/UP, SC/TN) and
  a low-selectivity case expected to include cold-start (approximate)
  admission-probability rows.
- The counsellor's structured-retrieval numbers (models/counsellor_retrieval)
  for a named-college question, with and without a student profile.
- The similarity feature's backend-dependent input: build_all_profiles,
  which is the only part of models/similarity.py that touches the database
  (the FAISS index and get_similar_colleges never do, at build time or
  request time, so there is nothing backend-dependent left to compare there
  once build_all_profiles matches).

Usage: python -m db.parity_check --postgres-url postgresql://...
The SQLite side always uses the shipped college_compass.db (the migration's
real source of truth).
"""

import argparse
import sys

import pandas as pd
from sentence_transformers import SentenceTransformer
from sqlalchemy import text as sa_text

from api.eligibility import build_forecasts, load_reference_tables, merge_forecasts_with_colleges
from db.connection import DEFAULT_DATABASE_URL, get_engine
from models.admission_probability import load_artifacts as load_probability_artifacts
from models.counsellor_retrieval import build_context_bundle, build_lookup_cache
from models.ranker import load_ranker
from models.similarity import EMBEDDING_MODEL_NAME, build_all_profiles, load_similarity_index

import api.main as api_main

STUDENT_CASES = [
    ("OPEN rank 5000, no home state", {"jee_rank": 5000, "category": "OPEN"}),
    ("OPEN rank 5000, home state Delhi", {"jee_rank": 5000, "category": "OPEN", "home_state": "Delhi"}),
    ("OBC-NCL category rank 8000, home state Uttar Pradesh", {"jee_rank": 8000, "category": "OBC-NCL", "home_state": "Uttar Pradesh"}),
    ("SC category rank 3000, home state Tamil Nadu", {"jee_rank": 3000, "category": "SC", "home_state": "Tamil Nadu"}),
    ("OPEN rank 45000, no home state - expected to include cold-start rows", {"jee_rank": 45000, "category": "OPEN"}),
]

COUNSELLOR_CASES = [
    ("What is the closing rank for computer science at IIT Bombay?", None),
    ("What is the closing rank for computer science at IIT Bombay?", {"jee_rank": 500, "category": "OPEN"}),
    ("Tell me about MNIT Jaipur cutoffs", None),
]


def build_environment(database_url, ranker, probability_artifacts, similarity_bundle, embedding_model):
    """Everything compute_recommendation and build_context_bundle need,
    loaded through this one database_url - the backend-dependent half of
    model_state. ranker/probability_artifacts/similarity_bundle/embedding_model
    are trained/built artifacts loaded from disk, not the database, so they
    are shared across both environments rather than reloaded per backend.
    """
    reference_tables = load_reference_tables(database_url)
    forecasts = build_forecasts(database_url)
    merged_forecasts = merge_forecasts_with_colleges(forecasts, reference_tables[0])
    counsellor_lookup = build_lookup_cache(database_url)
    return {
        "reference_tables": reference_tables,
        "merged_forecasts": merged_forecasts,
        "known_states": set(reference_tables[0]["state"].dropna().unique().tolist()),
        "counsellor_lookup": counsellor_lookup,
        "ranker": ranker,
        "probability_artifacts": probability_artifacts,
        "similarity_bundle": similarity_bundle,
        "embedding_model": embedding_model,
    }


def _run_recommend(model_state, request_dict):
    api_main.model_state.clear()
    api_main.model_state.update(model_state)
    request = api_main.RecommendRequest(**request_dict)
    return api_main.compute_recommendation(request)


def compare_recommend(sqlite_state, postgres_state):
    print("\n=== /recommend parity ===")
    failures = []
    for label, request_dict in STUDENT_CASES:
        sqlite_result = _run_recommend(sqlite_state, request_dict)
        postgres_result = _run_recommend(postgres_state, request_dict)

        total = sum(sqlite_result["counts"].values())
        approx_count = sum(1 for band in ("safe", "moderate", "dream") for r in sqlite_result[band] if r["probability_is_approximate"])

        if sqlite_result == postgres_result:
            print(f"  MATCH  {label}  ({total} college-branches, {approx_count} approximate)")
        else:
            failures.append(label)
            print(f"  MISMATCH  {label}")
            _diff_dicts(sqlite_result, postgres_result)
    return failures


def _diff_dicts(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            _diff_dicts(a.get(key), b.get(key), f"{path}.{key}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            print(f"    {path}: length {len(a)} vs {len(b)}")
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _diff_dicts(x, y, f"{path}[{i}]")
    elif a != b:
        print(f"    {path}: sqlite={a!r}  postgres={b!r}")


def compare_counsellor_retrieval(sqlite_state, postgres_state):
    print("\n=== counsellor structured-retrieval parity (numbers only) ===")
    failures = []
    for question, student_profile in COUNSELLOR_CASES:
        sqlite_bundle = build_context_bundle(question, student_profile, sqlite_state)
        postgres_bundle = build_context_bundle(question, student_profile, postgres_state)

        sqlite_records = sorted(sqlite_bundle["records"], key=lambda r: (r["college_id"], r["field"], str(r["value"])))
        postgres_records = sorted(postgres_bundle["records"], key=lambda r: (r["college_id"], r["field"], str(r["value"])))

        label = f"{question!r} (profile={student_profile})"
        if sqlite_records == postgres_records and sqlite_bundle["college_ids"] == postgres_bundle["college_ids"]:
            print(f"  MATCH  {label}  ({len(sqlite_records)} records)")
        else:
            failures.append(label)
            print(f"  MISMATCH  {label}")
            _diff_dicts(sqlite_records, postgres_records)
    return failures


def compare_similarity_profiles(sqlite_url, postgres_url):
    print("\n=== similarity profile-building parity ===")
    sqlite_profiles, sqlite_colleges = build_all_profiles(sqlite_url)
    postgres_profiles, postgres_colleges = build_all_profiles(postgres_url)

    failures = []
    if sqlite_profiles != postgres_profiles:
        failures.append("profiles")
        print("  MISMATCH  profile text differs")
        for cid in sorted(set(sqlite_profiles) | set(postgres_profiles)):
            if sqlite_profiles.get(cid) != postgres_profiles.get(cid):
                print(f"    {cid}: sqlite={sqlite_profiles.get(cid)!r}  postgres={postgres_profiles.get(cid)!r}")
    else:
        print(f"  MATCH  profile text identical for all {len(sqlite_profiles)} colleges")

    sqlite_sorted = sqlite_colleges.sort_values("college_id").reset_index(drop=True)
    postgres_sorted = postgres_colleges.sort_values("college_id").reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(sqlite_sorted, postgres_sorted, check_dtype=False, check_like=True)
        print(f"  MATCH  colleges table identical ({len(sqlite_sorted)} rows)")
    except AssertionError as exc:
        failures.append("colleges_table")
        print(f"  MISMATCH  colleges table differs:\n{exc}")

    return failures


def _row_counts(database_url, table_names):
    engine = get_engine(database_url)
    with engine.connect() as conn:
        return {name: conn.execute(sa_text(f"SELECT COUNT(*) FROM {name}")).scalar() for name in table_names}


def compare_row_counts(sqlite_url, postgres_url):
    print("\n=== row count parity ===")
    table_names = ["colleges", "programs", "cutoffs", "seat_counts", "nirf_rankings", "reference_metadata"]
    sqlite_counts = _row_counts(sqlite_url, table_names)
    postgres_counts = _row_counts(postgres_url, table_names)

    failures = []
    for name in table_names:
        if sqlite_counts[name] == postgres_counts[name]:
            print(f"  MATCH  {name}: {sqlite_counts[name]}")
        else:
            failures.append(name)
            print(f"  MISMATCH  {name}: sqlite={sqlite_counts[name]} postgres={postgres_counts[name]}")
    return failures


def run(postgres_url, sqlite_url=None):
    sqlite_url = sqlite_url or DEFAULT_DATABASE_URL

    print("[parity] loading shared, backend-independent artifacts (ranker, probability calibration, similarity index)...")
    ranker = load_ranker()
    probability_artifacts = load_probability_artifacts()
    similarity_bundle = load_similarity_index()
    embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    print(f"[parity] building sqlite environment ({sqlite_url})...")
    sqlite_state = build_environment(sqlite_url, ranker, probability_artifacts, similarity_bundle, embedding_model)

    print(f"[parity] building postgres environment...")
    postgres_state = build_environment(postgres_url, ranker, probability_artifacts, similarity_bundle, embedding_model)

    all_failures = []
    all_failures += compare_row_counts(sqlite_url, postgres_url)
    all_failures += compare_recommend(sqlite_state, postgres_state)
    all_failures += compare_counsellor_retrieval(sqlite_state, postgres_state)
    all_failures += compare_similarity_profiles(sqlite_url, postgres_url)

    print("\n=== summary ===")
    if all_failures:
        print(f"FAILED: {len(all_failures)} mismatch(es): {all_failures}")
        return False
    print("PASSED: every comparison identical between sqlite and postgres.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-url", required=True, help="Postgres URL already migrated via db.migrate_to_postgres")
    parser.add_argument("--sqlite-url", default=None, help="defaults to the shipped SQLite file")
    args = parser.parse_args()

    passed = run(args.postgres_url, args.sqlite_url)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
