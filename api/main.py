"""FastAPI backend: the first working end-to-end path from a student's
input to a real ranked, banded college list.

Models load once at startup, not per request. That matters more than it
sounds: a freshly loaded LGBMRanker's first predict() call costs about 1.7
seconds (some one-time internal setup cost), while every call after that
costs about 0.02 seconds - confirmed directly by timing both. Paying that
1.7 seconds once at boot, via the warmup call below, is the difference
between a slow first request and every request being fast.

This does not retrain or change the regressor or ranker. It loads the
already-trained artifacts and calls the already-built eligibility filter
and ranker, exactly as they exist.
"""

import os
import re
import sys
import threading
import traceback
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import pandas as pd
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import bindparam, text
from typing import Literal, Optional

from api.eligibility import StudentProfile, build_forecasts, load_reference_tables, merge_forecasts_with_colleges
from api.report_data import build_report_data
from api.report_pdf import render_report_pdf
from db.connection import get_backend_name, get_database_url, get_engine, redact_database_url
from models.admission_probability import load_artifacts as load_probability_artifacts, predict_admission_probability
from models.counsellor import generate_answer
from models.counsellor_retrieval import build_context_bundle, build_lookup_cache
from models.ranker import load_ranker, score_candidates_for_student
from models.round_forecast import project_rounds
from models.similarity import get_similar_colleges, load_similarity_index
from models.trend import classify_trend

MIN_RANK = 1
MAX_RANK = 2_000_000
VALID_CATEGORIES = ["OPEN", "EWS", "OBC-NCL", "SC", "ST", "OPEN (PwD)", "EWS (PwD)", "OBC-NCL (PwD)", "SC (PwD)", "ST (PwD)"]
FORECAST_YEAR = 2025
SIMILAR_TOP_K = 5
SIMILAR_NOTE = "Similar by type, location, ranking, and programs offered - not a personalized match for you specifically."

model_state = {}


def _boot_failed():
    """Called from the loader's except block. The load runs in a background
    thread so the port binds first; an exception there would only end the
    thread and leave a server that answers /health forever without models,
    which a deploy check would call healthy. Exit status 3 is what a failed
    lifespan gave uvicorn before, so a broken deploy still fails loudly.
    """
    traceback.print_exc()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(3)


def _load_models():
    print("[api] loading reference data and forecasts...")
    reference_tables = load_reference_tables()
    forecasts = build_forecasts()
    merged_forecasts = merge_forecasts_with_colleges(forecasts, reference_tables[0])

    print("[api] loading trained ranker...")
    ranker = load_ranker()

    print("[api] loading calibrated admission-probability artifacts...")
    probability_artifacts = load_probability_artifacts()

    print("[api] loading similar-college retrieval index...")
    similarity_bundle = load_similarity_index()
    if similarity_bundle is None:
        print("[api] no similarity index found on disk - /similar/{college_id} will return 503 until `python -m models.similarity` is run")

    print("[api] loading counsellor college/branch name lookup cache...")
    counsellor_lookup = build_lookup_cache()

    print("[api] warming up the ranker's first-prediction cost at boot, not on the first real request...")
    warmup_student = StudentProfile(jee_rank=50000, category="OPEN")
    score_candidates_for_student(ranker, warmup_student, merged_forecasts, reference_tables)

    # Published last, in one update, so /health only reports models_loaded
    # once every endpoint can actually serve (warm-up included).
    model_state.update(
        reference_tables=reference_tables,
        merged_forecasts=merged_forecasts,
        ranker=ranker,
        probability_artifacts=probability_artifacts,
        known_states=set(reference_tables[0]["state"].dropna().unique().tolist()),
        similarity_bundle=similarity_bundle,
        counsellor_lookup=counsellor_lookup,
    )

    # The ONNX encoder (models/onnx_encoder.py) is deliberately not loaded
    # here - it's only needed for /chat's semantic retrieval path, and even
    # importing onnxruntime/tokenizers has a real cost. See
    # models/counsellor_retrieval.py's _get_embedding_model, which loads it
    # lazily on first semantic /chat call and caches it in model_state same
    # as every other artifact here.
    print("[api] models loaded and ready")


def _load_in_background():
    try:
        _load_models()
    except Exception:
        _boot_failed()


@asynccontextmanager
async def lifespan(app: FastAPI):
    backend_name = get_backend_name()
    print(f"[api] database backend: {backend_name} ({redact_database_url()})")
    model_state["backend_name"] = backend_name

    # Heavy load off the event loop so the port binds and /health answers
    # during it. Until it finishes, every endpoint that needs a model returns
    # its existing 503.
    threading.Thread(target=_load_in_background, daemon=True).start()
    yield
    model_state.clear()


app = FastAPI(title="College Compass API", lifespan=lifespan)

# CORS_ORIGINS is a comma-separated list of allowed frontend origins. Unset
# defaults to "*" (any origin) for local dev, where the frontend runs on an
# arbitrary Vite dev-server port. Set it to the real frontend origin(s) for
# any deploy, e.g. CORS_ORIGINS=https://collegecompass.example.com.
cors_origins = [o.strip() for o in (os.environ.get("CORS_ORIGINS") or "").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"], allow_headers=["*"])


class RecommendRequest(BaseModel):
    jee_rank: int = Field(..., description="Overall CRL rank for OPEN; category rank (not CRL) for EWS/OBC-NCL/SC/ST")
    category: str
    home_state: Optional[str] = None
    preferred_branch_category: Literal["cs_adjacent", "core", "any"] = "any"
    budget_annual_lakhs: Optional[float] = None
    wants_top_nirf: bool = False
    institute_ownership_pref: Literal["government", "ppp", "both"] = "both"
    prefers_home_state: bool = False

    @field_validator("jee_rank")
    @classmethod
    def rank_in_bounds(cls, v):
        if not (MIN_RANK <= v <= MAX_RANK):
            raise ValueError(f"jee_rank must be between {MIN_RANK} and {MAX_RANK}")
        return v

    @field_validator("category")
    @classmethod
    def category_known(cls, v):
        if v not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {VALID_CATEGORIES}")
        return v


def _require_loaded():
    if "ranker" not in model_state:
        raise HTTPException(status_code=503, detail="models are still loading, try again shortly")


def _memory_readout(status_path="/proc/self/status"):
    """Resident memory and its high-water mark in MB, from /proc on Linux;
    null for both elsewhere. Render's free tier has no memory graph, so this
    is the only way to read the real figure from production. The peak is the
    one an OOM kill acts on, and a boot peak is gone by the time anyone polls.
    """
    readout = {"rss_mb": None, "rss_peak_mb": None}
    fields = {"VmRSS": "rss_mb", "VmHWM": "rss_peak_mb"}
    try:
        with open(status_path) as f:
            for line in f:
                name, _, rest = line.partition(":")
                if name in fields:
                    readout[fields[name]] = round(int(rest.split()[0]) / 1024, 1)
    except OSError:
        pass
    return readout


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    loaded = "ranker" in model_state and "merged_forecasts" in model_state
    return {"status": "ok" if loaded else "not_ready", "models_loaded": loaded, **_memory_readout()}


@app.get("/meta")
def meta():
    """Lets the frontend populate its home-state dropdown from the data the
    backend actually has, instead of a hardcoded list that could drift from it.
    Also reports whether the counsellor's data is loaded and whether an LLM
    endpoint has been configured - presence only, never the value, so a real
    key or internal endpoint is never echoed back to a client.
    """
    _require_loaded()
    return {
        "categories": VALID_CATEGORIES,
        "states": sorted(model_state.get("known_states", [])),
        "counsellor_available": "counsellor_lookup" in model_state,
        "llm_endpoint_configured": bool(os.environ.get("LLM_ENDPOINT")),
        "database_backend": model_state.get("backend_name", get_backend_name()),
    }


def _row_to_result(rank_order, row, student_rank, probability_artifacts, category, history_cache):
    has_lag = row["prediction_source"] == "delta_model"
    admission_probability = predict_admission_probability(
        row["predicted_closing_rank"], student_rank, has_lag, probability_artifacts
    )

    # Additive-only field (docs/Rules.md section 7): a classifier exception
    # drops just this row's trend object, never the response it's attached to.
    key = (row["college_id"], row["program_id"], category, row["quota_used"])
    try:
        trend = None if history_cache is None else asdict(classify_trend(history_cache.get(key, [])))
    except Exception as exc:
        print(f"[api] trend classification failed for {key}: {exc}")
        trend = None

    # Additive-only field (docs/Rules.md section 7), same pattern as trend
    # above: a projection failure drops just this row's rounds array, never
    # the response. Computed on demand from predicted_closing_rank, nothing
    # queried or materialized (docs/Rules.md section 8).
    try:
        rounds = project_rounds(int(row["predicted_closing_rank"]), category, row["branch_name"])
    except Exception as exc:
        print(f"[api] round projection failed for {key}: {exc}")
        rounds = None

    return {
        "rank_order": rank_order,
        "college_id": row["college_id"],
        "program_id": row["program_id"],
        "college_name": row["college_name"],
        "branch_name": row["branch_name"],
        "institute_type": row["institute_type"],
        "state": row["state"] if pd.notna(row["state"]) else None,
        "nirf_rank": int(row["nirf_rank"]) if pd.notna(row["nirf_rank"]) else None,
        "band": row["band"],
        "quota_used": row["quota_used"],
        "predicted_closing_rank": int(row["predicted_closing_rank"]),
        "margin": int(row["margin"]),
        "fees_annual_lakhs": float(row["fees_annual_lakhs"]) if pd.notna(row["fees_annual_lakhs"]) else None,
        "admission_probability": admission_probability,
        "probability_is_approximate": not has_lag,
        "trend": trend,
        "rounds": rounds,
    }


def compute_recommendation(request: RecommendRequest):
    """The full /recommend computation, factored out so /report can build a
    PDF from the exact same eligibility/ranker/probability output instead of
    recomputing anything.
    """
    _require_loaded()

    if request.home_state and request.home_state not in model_state["known_states"]:
        raise HTTPException(
            status_code=400,
            detail=f"unrecognized home_state {request.home_state!r}. Known states: {sorted(model_state['known_states'])}",
        )

    student = StudentProfile(
        jee_rank=request.jee_rank,
        category=request.category,
        home_state=request.home_state,
        preferred_branch_category=request.preferred_branch_category,
        budget_annual_lakhs=request.budget_annual_lakhs,
        wants_top_nirf=request.wants_top_nirf,
        institute_ownership_pref=request.institute_ownership_pref,
        prefers_home_state=request.prefers_home_state,
    )

    scored = score_candidates_for_student(model_state["ranker"], student, model_state["merged_forecasts"], model_state["reference_tables"])
    probability_artifacts = model_state["probability_artifacts"]
    history_cache = _get_cutoff_history_cache()

    bands = {"safe": [], "moderate": [], "dream": []}
    if not scored.empty:
        for band in bands:
            band_df = scored[scored["band"] == band]
            bands[band] = [
                _row_to_result(i + 1, row, request.jee_rank, probability_artifacts, request.category, history_cache)
                for i, (_, row) in enumerate(band_df.iterrows())
            ]

    return {
        "based_on_year": FORECAST_YEAR,
        "counts": {band: len(rows) for band, rows in bands.items()},
        "safe": bands["safe"],
        "moderate": bands["moderate"],
        "dream": bands["dream"],
    }


@app.post("/recommend")
def recommend(request: RecommendRequest):
    return compute_recommendation(request)


def _report_filename(request: RecommendRequest):
    safe_category = re.sub(r"[^A-Za-z0-9]+", "_", request.category).strip("_")
    return f"college_compass_report_{safe_category}_{request.jee_rank}.pdf"


@app.post("/report")
def report(request: RecommendRequest):
    """Downloadable PDF counselling report - reuses compute_recommendation's
    output exactly, so every figure in the PDF is the same one /recommend
    already served for this student. See api/report_data.py and
    api/report_pdf.py.
    """
    recommend_response = compute_recommendation(request)
    report_data = build_report_data(request, recommend_response)
    pdf_bytes = render_report_pdf(report_data)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_report_filename(request)}"'},
    )


@app.get("/similar/{college_id}")
def similar(college_id: str):
    """Item-to-item retrieval only: colleges near this one by type, location,
    ranking, and programs offered. Not personalized to any student, and not a
    quality judgment - see SIMILAR_NOTE. Loads on demand, independent of
    /recommend, since it's a "see more" affordance, not part of the main flow.
    """
    _require_loaded()
    similarity_bundle = model_state.get("similarity_bundle")
    if similarity_bundle is None:
        raise HTTPException(status_code=503, detail="similarity index is not built yet")

    index, metadata = similarity_bundle
    neighbours = get_similar_colleges(college_id, index, metadata, k=SIMILAR_TOP_K)
    return {"college_id": college_id, "similar": neighbours, "note": SIMILAR_NOTE}


# Female-only seats are never modeled anywhere in this product (see
# models/regressor_dataset.py) - excluded here too, so the trend chart never
# shows a quota line the student was never scored against. Pre-2018 rows
# (JoSAA didn't gender-split reporting yet) apply to everyone and stay in.
FEMALE_ONLY_GENDER_SEAT_TYPE = "Female-only (including Supernumerary)"


def _history_row(row):
    return {
        "year": int(row.year),
        "closing_rank": int(row.closing_rank),
        "round": int(row.round) if row.round is not None else None,
        "opening_rank": int(row.opening_rank) if row.opening_rank is not None else None,
    }


def get_cutoff_history(college_id: str, program_id: str, category: str, quota: str, database_url=None):
    """Straight, read-only lookup against the existing cutoffs table for the
    College detail chart - no recompute, no ML. An unknown combination just
    comes back empty; the frontend shows that honestly rather than as an error.

    JoSAA reports a closing rank per round (1 through 6 or 7 most years), so
    a raw per-row pull returns several points per year - a jagged mess, not a
    trend. This keeps only the last round each year (the settled closing
    rank), treating a null round (2023+ rows, reported without a round
    breakdown) as already final rather than as round zero. `round` and
    `opening_rank` describe that same settled row; a null round means the
    year genuinely has no round breakdown (2023+), not round zero.
    """
    engine = get_engine(database_url)
    query = text(
        """
        WITH ranked AS (
            SELECT year, round, opening_rank, closing_rank,
                   ROW_NUMBER() OVER (
                       PARTITION BY year
                       ORDER BY (round IS NULL) ASC, round DESC
                   ) AS rn
            FROM cutoffs
            WHERE college_id = :college_id
              AND program_id = :program_id
              AND category = :category
              AND quota = :quota
              AND gender_seat_type != :excluded_gender
        )
        SELECT year, round, opening_rank, closing_rank FROM ranked WHERE rn = 1 ORDER BY year
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(
            query,
            {
                "college_id": college_id,
                "program_id": program_id,
                "category": category,
                "quota": quota,
                "excluded_gender": FEMALE_ONLY_GENDER_SEAT_TYPE,
            },
        ).fetchall()
    return [_history_row(row) for row in rows]


def get_cutoff_history_bulk(keys, database_url=None):
    """Bulk version of get_cutoff_history for many (college_id, program_id,
    category, quota) keys in one query - a candidate set from /recommend can
    carry 800+ rows, and calling the single-key query per row would turn one
    request into hundreds of round trips. Not a second endpoint: a query-
    layer function for Phase 2's trend assembly to call in process.

    Same settled-round-per-year selection as the single-key query, so the two
    agree row for row on any key they're both asked about (see
    tests/test_cutoffs_endpoint.py). Filters by the distinct column values
    present across all requested keys, then matches exact tuples in Python -
    simpler and more portable than a composite-key SQL IN clause, and the
    distinct-value lists stay small even for an 800-row candidate set (one
    category, a handful of quotas, at most a few hundred colleges/programs).
    """
    unique_keys = list(dict.fromkeys(keys))
    if not unique_keys:
        return {}

    college_ids = sorted({k[0] for k in unique_keys})
    program_ids = sorted({k[1] for k in unique_keys})
    categories = sorted({k[2] for k in unique_keys})
    quotas = sorted({k[3] for k in unique_keys})

    engine = get_engine(database_url)
    query = text(
        """
        WITH ranked AS (
            SELECT college_id, program_id, category, quota, year, round, opening_rank, closing_rank,
                   ROW_NUMBER() OVER (
                       PARTITION BY college_id, program_id, category, quota, year
                       ORDER BY (round IS NULL) ASC, round DESC
                   ) AS rn
            FROM cutoffs
            WHERE college_id IN :college_ids
              AND program_id IN :program_ids
              AND category IN :categories
              AND quota IN :quotas
              AND gender_seat_type != :excluded_gender
        )
        SELECT college_id, program_id, category, quota, year, round, opening_rank, closing_rank
        FROM ranked WHERE rn = 1 ORDER BY college_id, program_id, category, quota, year
        """
    ).bindparams(
        bindparam("college_ids", expanding=True),
        bindparam("program_ids", expanding=True),
        bindparam("categories", expanding=True),
        bindparam("quotas", expanding=True),
    )
    with engine.connect() as conn:
        rows = conn.execute(
            query,
            {
                "college_ids": college_ids,
                "program_ids": program_ids,
                "categories": categories,
                "quotas": quotas,
                "excluded_gender": FEMALE_ONLY_GENDER_SEAT_TYPE,
            },
        ).fetchall()

    wanted = set(unique_keys)
    result = {key: [] for key in unique_keys}
    for row in rows:
        key = (row.college_id, row.program_id, row.category, row.quota)
        if key in wanted:
            result[key].append(_history_row(row))
    return result


def build_cutoff_history_cache(database_url=None):
    """Settled year/closing-rank history for every (college_id, program_id,
    category, quota) key in the cutoffs table, in one query.

    Cutoff history is static between reingests - it does not change request
    to request or deploy to deploy. get_cutoff_history_bulk() re-derives the
    same settled-round-per-year table on every /recommend call, which timed
    at 360-450ms even with the composite index (KNOWN_ISSUES.md), because
    the settled-round window function still runs over the matched rows after
    the index narrows the scan. Building this table once and reusing it
    turns that into a dict lookup.

    Shape: {(college_id, program_id, category, quota): [(year, closing_rank), ...]}.
    Narrower than get_cutoff_history_bulk's row shape on purpose - round and
    opening_rank aren't inputs to trend classification (models/trend.py), so
    they're dropped here rather than carried in a cache meant to stay small.
    """
    engine = get_engine(database_url)
    query = text(
        """
        WITH ranked AS (
            SELECT college_id, program_id, category, quota, year, closing_rank,
                   ROW_NUMBER() OVER (
                       PARTITION BY college_id, program_id, category, quota, year
                       ORDER BY (round IS NULL) ASC, round DESC
                   ) AS rn
            FROM cutoffs
            WHERE gender_seat_type != :excluded_gender
        )
        SELECT college_id, program_id, category, quota, year, closing_rank
        FROM ranked WHERE rn = 1
        """
    )
    # Streamed, not .fetchall() - the intermediate 50k+ Row objects a
    # one-shot fetch would hold all at once are pure overhead once each has
    # been folded into cache. college_id/program_id/category/quota repeat
    # across many rows (once per year a key has data, and again across every
    # category/quota a college-program pair is offered under) - interned so
    # those repeats share one string object instead of a fresh copy each row.
    cache = {}
    with engine.connect() as conn:
        result = conn.execute(query, {"excluded_gender": FEMALE_ONLY_GENDER_SEAT_TYPE})
        for row in result:
            key = (sys.intern(row.college_id), sys.intern(row.program_id), sys.intern(row.category), sys.intern(row.quota))
            cache.setdefault(key, []).append((int(row.year), int(row.closing_rank)))
    return cache


_cutoff_cache_lock = threading.Lock()


def _get_cutoff_history_cache():
    """Lazy, cached in model_state exactly like _get_embedding_model in
    models/counsellor_retrieval.py - built on the first /recommend call that
    needs it, not at import time and not eagerly at startup.

    Trend is an additive field (docs/Rules.md section 8), so a failed build
    returns None, which _row_to_result turns into trend: null, instead of
    failing /recommend. The failure is not cached: the next request retries.
    The lock makes concurrent first requests wait for one build instead of
    each making their own (that transient cost ~37 MB extra for four at once).
    """
    cache = model_state.get("cutoff_history_cache")
    if cache is not None:
        return cache
    with _cutoff_cache_lock:
        cache = model_state.get("cutoff_history_cache")
        if cache is None:
            try:
                cache = model_state["cutoff_history_cache"] = build_cutoff_history_cache()
            except Exception as exc:
                print(f"[api] cutoff history cache build failed, serving without trends: {exc}")
                return None
    return cache


@app.get("/cutoffs")
def cutoffs(college_id: str, program_id: str, category: str, quota: str):
    """Year-over-year closing-rank history for one college, branch, category,
    and quota - feeds the College detail trend chart. The only backend
    endpoint added for the frontend swap; everything else already existed.
    """
    history = get_cutoff_history(college_id, program_id, category, quota)
    return {"college_id": college_id, "program_id": program_id, "category": category, "quota": quota, "history": history}


class ChatRequest(BaseModel):
    question: str
    student_profile: Optional[RecommendRequest] = None


@app.post("/chat")
def chat(request: ChatRequest):
    """Grounded counsellor chat: routes the question to structured lookup
    (a named college) and/or semantic retrieval (the existing similarity
    index) for a context bundle, then generates an answer that is
    numerically validated in code before it's ever returned - see
    models/counsellor.py. Never blocks on /recommend; this is a separate,
    on-demand path.
    """
    if "counsellor_lookup" not in model_state:
        raise HTTPException(status_code=503, detail="counsellor data is still loading, try again shortly")

    student_profile_dict = None
    if request.student_profile is not None:
        if request.student_profile.home_state and request.student_profile.home_state not in model_state["known_states"]:
            raise HTTPException(
                status_code=400,
                detail=f"unrecognized home_state {request.student_profile.home_state!r}. Known states: {sorted(model_state['known_states'])}",
            )
        student_profile_dict = request.student_profile.model_dump()

    bundle = build_context_bundle(request.question, student_profile_dict, model_state)
    result = generate_answer(request.question, bundle)

    return {
        "answer": result["answer"],
        "source_college_ids": result["source_college_ids"],
        "blocked_ungrounded_figure": result["blocked_ungrounded_figure"],
    }


# Serves the built frontend (`npm run build` in frontend/) when it exists, so
# a single `uvicorn` process can serve the whole app in production. In local
# dev, frontend/dist doesn't exist (the Vite dev server runs separately on
# its own port), so this stays inert and doesn't interfere with that setup.
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if FRONTEND_DIST.is_dir():
    frontend_assets = FRONTEND_DIST / "assets"
    if frontend_assets.is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_assets), name="frontend-assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        """Any real static file (favicon, manifest) is served directly;
        anything else is a client-side route, so index.html handles it and
        react-router takes over - same fallback the Vite dev proxy does.
        """
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
