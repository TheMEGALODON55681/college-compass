"""Loads the real current data from the existing SQLite database into
Postgres. Run with the target Postgres URL in DATABASE_URL:

    DATABASE_URL=postgresql://user:pass@host:5432/college_compass python -m db.migrate_to_postgres

Or pass --source/--target explicitly (used by db/parity_check.py so it can
point at a throwaway test Postgres without touching the environment).

Idempotent: rerunning this against the same target clears each table and
reloads it fresh from the source SQLite file, rather than appending on top of
a previous run. Nothing is deduped, dropped, or fabricated - the row count
loaded into Postgres always equals the row count read from SQLite, checked
explicitly before this script reports success.

The known SQLite-to-Postgres gotcha this script exists to handle: a nullable
Integer column with any NULLs (e.g. colleges.nirf_rank_latest, cutoffs.round)
comes back from pd.read_sql as float64 with NaN standing in for NULL, because
plain numpy has no nullable integer dtype. Writing a 3.0 into a Postgres
INTEGER column is not the same as writing 3, and NaN is not the same as SQL
NULL - both a type and a semantics gotcha. Every nullable Integer column
(read from db/models.py's own column definitions, not hardcoded per table) is
cast to pandas' nullable "Int64" dtype before being written, so whole numbers
go in as real integers and missing values go in as real NULLs.
"""

import argparse

import pandas as pd
from sqlalchemy import Integer, text

from db.connection import DEFAULT_DATABASE_URL, get_backend_name, get_database_url, get_engine, redact_database_url
from db.models import Base

# Parents before children, so FK constraints never trip during insert.
# reference_metadata's own primary key is college_id, so it's an FK-holding
# "child" of colleges despite not depending on programs.
TABLE_LOAD_ORDER = ["colleges", "programs", "cutoffs", "seat_counts", "nirf_rankings", "reference_metadata"]


def _nullable_integer_columns(table_name):
    table = Base.metadata.tables[table_name]
    return [c.name for c in table.columns if isinstance(c.type, Integer) and c.nullable]


def _coerce_nullable_integers(df, table_name):
    for col in _nullable_integer_columns(table_name):
        if col in df.columns:
            df[col] = df[col].astype("Int64")
    return df


def _row_counts(engine, table_names):
    counts = {}
    with engine.connect() as conn:
        for name in table_names:
            counts[name] = conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
    return counts


def migrate(source_url, target_url):
    if get_backend_name(target_url) != "postgres":
        raise SystemExit(f"target must be a postgres:// URL, got backend {get_backend_name(target_url)!r}")

    source_engine = get_engine(source_url)
    target_engine = get_engine(target_url)

    print(f"[migrate] source: {redact_database_url(source_url)}")
    print(f"[migrate] target: {redact_database_url(target_url)}")

    print("[migrate] creating schema on target (no-op for tables that already exist)...")
    Base.metadata.create_all(target_engine)

    source_counts = _row_counts(source_engine, TABLE_LOAD_ORDER)

    print("[migrate] clearing target tables (children before parents) for an idempotent reload...")
    with target_engine.begin() as conn:
        for name in reversed(TABLE_LOAD_ORDER):
            conn.execute(text(f"DELETE FROM {name}"))

    for name in TABLE_LOAD_ORDER:
        df = pd.read_sql(f"SELECT * FROM {name}", source_engine)
        df = _coerce_nullable_integers(df, name)
        df.to_sql(name, target_engine, if_exists="append", index=False, chunksize=2000)
        print(f"[migrate] loaded {len(df)} rows into {name}")

    target_counts = _row_counts(target_engine, TABLE_LOAD_ORDER)

    print("\n[migrate] row counts (source -> target):")
    mismatches = []
    for name in TABLE_LOAD_ORDER:
        marker = "OK" if source_counts[name] == target_counts[name] else "MISMATCH"
        print(f"  {name}: {source_counts[name]} -> {target_counts[name]}  [{marker}]")
        if source_counts[name] != target_counts[name]:
            mismatches.append(name)

    if mismatches:
        raise SystemExit(f"[migrate] row count mismatch after migration for: {mismatches} - migration is NOT complete")

    print("\n[migrate] every table's row count matches. Migration complete.")
    return source_counts, target_counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_DATABASE_URL, help="source database URL (default: the shipped SQLite file)")
    parser.add_argument("--target", default=None, help="target Postgres URL (default: DATABASE_URL env var)")
    args = parser.parse_args()

    target_url = args.target or get_database_url()
    migrate(args.source, target_url)


if __name__ == "__main__":
    main()
