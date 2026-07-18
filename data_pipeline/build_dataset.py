"""Loads the normalized tables into the dev database and prints a coverage report.

The coverage report is the pipeline's honesty check: it states plainly which
institute-type x year combinations have real data and which don't, rather
than letting a silent gap look like complete coverage downstream.
"""

import os

import pandas as pd

from data_pipeline.reference_data import load_reference_metadata
from data_pipeline.sources import PROCESSED_DIR
from db.connection import get_database_url, get_engine, redact_database_url
from db.models import Base


def load_processed_tables():
    return {
        "colleges": pd.read_parquet(os.path.join(PROCESSED_DIR, "colleges.parquet")),
        "programs": pd.read_parquet(os.path.join(PROCESSED_DIR, "programs.parquet")),
        "cutoffs": pd.read_parquet(os.path.join(PROCESSED_DIR, "cutoffs.parquet")),
        "seat_counts": pd.read_parquet(os.path.join(PROCESSED_DIR, "seat_counts.parquet")),
        "nirf_rankings": pd.read_parquet(os.path.join(PROCESSED_DIR, "nirf_rankings.parquet"))[
            ["nirf_id", "college_id", "year", "rank", "score"]
        ],
    }


def attach_latest_nirf_rank(colleges, nirf_rankings):
    latest = nirf_rankings.sort_values("year").drop_duplicates(subset="college_id", keep="last")
    rank_map = dict(zip(latest["college_id"], latest["rank"]))
    colleges = colleges.copy()
    colleges["nirf_rank_latest"] = colleges["college_id"].map(rank_map)
    return colleges


def print_coverage_report(cutoffs, colleges):
    """Computed from the actual loaded data rather than a fixed narrative, so
    this can't go stale the next time a source is added or removed - it said
    the 2021-2023 NIT/IIIT/GFTI gap was permanent right up until the sources
    that closed it were wired in, so the report itself needs to describe
    whatever is actually true of the data in front of it.
    """
    merged = cutoffs.merge(colleges[["college_id", "institute_type"]], on="college_id")
    pivot = merged.groupby(["year", "institute_type"])["closing_rank"].count().unstack(fill_value=0)
    print("\n=== Coverage report ===")
    print(pivot.to_string())

    print("\nCoverage by institute type (computed from the table above, not hardcoded):")
    for itype in pivot.columns:
        covered_years = sorted(int(y) for y in pivot.index[pivot[itype] > 0])
        all_years = sorted(int(y) for y in pivot.index)
        missing_years = [y for y in all_years if y not in covered_years]
        if missing_years:
            print(f"  {itype}: covered {covered_years}, GAP at {missing_years} - real absence, not fabricated")
        else:
            print(f"  {itype}: full coverage {covered_years[0]}-{covered_years[-1]}")

    print(
        "\n2025: only a seat matrix exists (seat counts), no closing ranks anywhere for 2025.\n"
        "The application's 'last year' baseline is 2024, the most recent real closing-rank year."
    )


def run(database_url=None):
    database_url = database_url or get_database_url()
    tables = load_processed_tables()
    tables["colleges"] = attach_latest_nirf_rank(tables["colleges"], tables["nirf_rankings"])
    reference_metadata = load_reference_metadata()

    print(f"[build_dataset] connecting to {redact_database_url(database_url)}")
    engine = get_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        tables["colleges"].to_sql("colleges", conn, if_exists="append", index=False)
        tables["programs"].to_sql("programs", conn, if_exists="append", index=False)
        tables["cutoffs"].to_sql("cutoffs", conn, if_exists="append", index=False)
        tables["seat_counts"].to_sql("seat_counts", conn, if_exists="append", index=False)
        tables["nirf_rankings"].to_sql("nirf_rankings", conn, if_exists="append", index=False)
        reference_metadata.to_sql("reference_metadata", conn, if_exists="append", index=False)

    print("[build_dataset] row counts loaded:")
    for name, df in tables.items():
        print(f"  {name}: {len(df)}")
    print(f"  reference_metadata: {len(reference_metadata)}")

    print_coverage_report(tables["cutoffs"], tables["colleges"])


if __name__ == "__main__":
    run()
