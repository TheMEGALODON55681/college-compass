"""Times the cutoffs bulk-history query (api/main.py's get_cutoff_history_bulk,
Phase 2's trend-assembly call) before and after the composite index db/models.py
now declares on cutoffs(college_id, program_id, category, quota), against
whatever DATABASE_URL points at.

Both timings use a fresh engine, never the cached one get_engine() normally
returns - reusing a connection would measure a warm pool the second time,
not the cold-connection cost a real request on Render free actually pays.
That is also why this only times one call per state instead of averaging
several: an average would mostly measure a warm connection too.

Idempotent and safe to rerun: the index is created with checkfirst=True, so
running this again after the index already exists just reports the current
(indexed) timing with no "before" figure, rather than erroring.

Usage: set DATABASE_URL to the target (unset defaults to the shipped SQLite
file, no setup needed), then:

    python -m db.measure_cutoff_index

Takes the connection string from DATABASE_URL only, never a command-line
argument, so a Postgres URL carrying credentials never lands in shell
history.
"""

import time

from sqlalchemy import inspect

import db.connection as connection
from api.eligibility import StudentProfile, build_forecasts, get_eligible_colleges, load_reference_tables
from api.main import get_cutoff_history_bulk
from db.connection import get_backend_name, get_database_url, redact_database_url
from db.models import Cutoff

INDEX_NAME = "ix_cutoffs_college_program_category_quota"
INDEX = next(idx for idx in Cutoff.__table__.indexes if idx.name == INDEX_NAME)

# Same representative student Phase 1 used to pull its 672-key sample, so
# this number is directly comparable to the 512 ms figure already recorded
# in BuildLog.md.
SAMPLE_STUDENT = StudentProfile(jee_rank=12480, category="OPEN", home_state="Delhi")


def _cold_engine(database_url):
    """A engine this process has never used, so the first query against it
    pays the real connection-establishment cost instead of reusing a pool
    get_engine() already warmed up earlier in this run.
    """
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    from sqlalchemy import create_engine

    return create_engine(database_url, connect_args=connect_args)


def _sample_keys(database_url):
    forecasts = build_forecasts(database_url)
    reference_tables = load_reference_tables(database_url)
    candidates = get_eligible_colleges(SAMPLE_STUDENT, forecasts=forecasts, reference_tables=reference_tables)
    return [(c["college_id"], c["program_id"], SAMPLE_STUDENT.category, c["quota_used"]) for c in candidates]


def _time_bulk_query(database_url, keys):
    engine = _cold_engine(database_url)
    try:
        # get_cutoff_history_bulk resolves its own engine from database_url via
        # get_engine(), which is cached - point it at a URL this cold engine
        # owns exclusively for this call by registering it in that cache first.
        connection._engine_cache[database_url] = engine
        start = time.perf_counter()
        history = get_cutoff_history_bulk(keys, database_url)
        elapsed_ms = (time.perf_counter() - start) * 1000
    finally:
        connection._engine_cache.pop(database_url, None)
        engine.dispose()
    return elapsed_ms, history


def _index_exists(database_url):
    engine = _cold_engine(database_url)
    try:
        existing = {row["name"] for row in inspect(engine).get_indexes("cutoffs")}
    finally:
        engine.dispose()
    return INDEX.name in existing


def run():
    database_url = get_database_url()
    backend = get_backend_name(database_url)
    print(f"[measure] backend: {backend} ({redact_database_url(database_url)})")

    keys = _sample_keys(database_url)
    print(f"[measure] sample candidate set: {len(keys)} distinct (college_id, program_id, category, quota) keys, "
          f"same student profile as the Phase 1 measurement (jee_rank=12480, OPEN, home_state=Delhi)")

    # _sample_keys warmed get_engine()'s cache building forecasts/reference
    # tables - drop that connection before timing anything, so a leftover
    # open connection isn't sitting on the target database (Postgres free
    # tiers cap concurrent connections low) during the cold measurements below.
    stale_engine = connection._engine_cache.pop(database_url, None)
    if stale_engine is not None:
        stale_engine.dispose()

    already_indexed = _index_exists(database_url)
    if already_indexed:
        print(f"[measure] {INDEX.name} already exists - no 'before' figure this run, timing the current (indexed) state only")
    else:
        before_ms, before_history = _time_bulk_query(database_url, keys)
        rows = sum(len(v) for v in before_history.values())
        print(f"[measure] before index: {before_ms:.1f} ms for {len(keys)} keys ({rows} history rows returned)")

        print(f"[measure] creating {INDEX.name} on cutoffs(college_id, program_id, category, quota)...")
        engine = _cold_engine(database_url)
        try:
            INDEX.create(bind=engine, checkfirst=True)
        finally:
            engine.dispose()

    after_ms, after_history = _time_bulk_query(database_url, keys)
    rows = sum(len(v) for v in after_history.values())
    print(f"[measure] after index: {after_ms:.1f} ms for {len(keys)} keys ({rows} history rows returned)")


if __name__ == "__main__":
    run()
