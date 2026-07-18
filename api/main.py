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
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

import pandas as pd
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sentence_transformers import SentenceTransformer
from typing import Literal, Optional

from api.eligibility import StudentProfile, build_forecasts, load_reference_tables, merge_forecasts_with_colleges
from api.report_data import build_report_data
from api.report_pdf import render_report_pdf
from db.connection import get_backend_name, get_database_url, redact_database_url
from models.admission_probability import load_artifacts as load_probability_artifacts, predict_admission_probability
from models.counsellor import generate_answer
from models.counsellor_retrieval import build_context_bundle, build_lookup_cache
from models.ranker import load_ranker, score_candidates_for_student
from models.similarity import EMBEDDING_MODEL_NAME, get_similar_colleges, load_similarity_index

MIN_RANK = 1
MAX_RANK = 2_000_000
VALID_CATEGORIES = ["OPEN", "EWS", "OBC-NCL", "SC", "ST", "OPEN (PwD)", "EWS (PwD)", "OBC-NCL (PwD)", "SC (PwD)", "ST (PwD)"]
FORECAST_YEAR = 2025
SIMILAR_TOP_K = 5
SIMILAR_NOTE = "Similar by type, location, ranking, and programs offered - not a personalized match for you specifically."

model_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    backend_name = get_backend_name()
    print(f"[api] database backend: {backend_name} ({redact_database_url()})")
    model_state["backend_name"] = backend_name

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

    print("[api] loading sentence-transformer for counsellor semantic retrieval...")
    embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    print("[api] loading counsellor college/branch name lookup cache...")
    counsellor_lookup = build_lookup_cache()

    model_state["reference_tables"] = reference_tables
    model_state["merged_forecasts"] = merged_forecasts
    model_state["ranker"] = ranker
    model_state["probability_artifacts"] = probability_artifacts
    model_state["known_states"] = set(reference_tables[0]["state"].dropna().unique().tolist())
    model_state["similarity_bundle"] = similarity_bundle
    model_state["embedding_model"] = embedding_model
    model_state["counsellor_lookup"] = counsellor_lookup

    print("[api] warming up the ranker's first-prediction cost at boot, not on the first real request...")
    warmup_student = StudentProfile(jee_rank=50000, category="OPEN")
    score_candidates_for_student(ranker, warmup_student, merged_forecasts, reference_tables)

    print("[api] warming up the embedding model's first-call cost at boot...")
    embedding_model.encode(["warmup query"], normalize_embeddings=True)

    print("[api] models loaded and ready")
    yield
    model_state.clear()


app = FastAPI(title="College Compass API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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


@app.get("/health")
def health():
    loaded = "ranker" in model_state and "merged_forecasts" in model_state
    return {"status": "ok" if loaded else "not_ready", "models_loaded": loaded}


@app.get("/meta")
def meta():
    """Lets the frontend populate its home-state dropdown from the data the
    backend actually has, instead of a hardcoded list that could drift from it.
    Also reports whether the counsellor's data is loaded and whether an LLM
    endpoint has been configured - presence only, never the value, so a real
    key or internal endpoint is never echoed back to a client.
    """
    return {
        "categories": VALID_CATEGORIES,
        "states": sorted(model_state.get("known_states", [])),
        "counsellor_available": "counsellor_lookup" in model_state,
        "llm_endpoint_configured": bool(os.environ.get("LLM_ENDPOINT")),
        "database_backend": model_state.get("backend_name", get_backend_name()),
    }


def _row_to_result(rank_order, row, student_rank, probability_artifacts):
    has_lag = row["prediction_source"] == "delta_model"
    admission_probability = predict_admission_probability(
        row["predicted_closing_rank"], student_rank, has_lag, probability_artifacts
    )
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
    }


def compute_recommendation(request: RecommendRequest):
    """The full /recommend computation, factored out so /report can build a
    PDF from the exact same eligibility/ranker/probability output instead of
    recomputing anything.
    """
    if "ranker" not in model_state:
        raise HTTPException(status_code=503, detail="models are still loading, try again shortly")

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

    bands = {"safe": [], "moderate": [], "dream": []}
    if not scored.empty:
        for band in bands:
            band_df = scored[scored["band"] == band]
            bands[band] = [
                _row_to_result(i + 1, row, request.jee_rank, probability_artifacts) for i, (_, row) in enumerate(band_df.iterrows())
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
    similarity_bundle = model_state.get("similarity_bundle")
    if similarity_bundle is None:
        raise HTTPException(status_code=503, detail="similarity index is not built yet")

    index, metadata = similarity_bundle
    neighbours = get_similar_colleges(college_id, index, metadata, k=SIMILAR_TOP_K)
    return {"college_id": college_id, "similar": neighbours, "note": SIMILAR_NOTE}


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
