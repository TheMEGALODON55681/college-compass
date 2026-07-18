"""Item-to-item similarity retrieval for "colleges like this one" - nearest
neighbours in a sentence-transformer embedding space over each college's
factual profile, indexed with FAISS (cosine similarity via inner product on
L2-normalized vectors).

This is similarity by type, location, ranking, and programs offered - NOT a
personalized or quality recommendation for any specific student. See
get_similar_colleges below.

Building the index is an offline step: run `python -m models.similarity`
whenever the underlying college data changes (new NIRF year, new branches,
new colleges added). The API loads the persisted index and mapping once at
startup - the same pattern models/ranker.py and models/admission_probability.py
already use for their trained artifacts - and never rebuilds per request.

Query-time retrieval never touches the sentence-transformer model at all: the
FAISS index already holds the normalized profile vector for every college, so
looking up a college's own vector with index.reconstruct is enough to search
its neighbours. The embedding model is only needed offline, at build time.
"""

import json
import os
import re

import faiss
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

from db.connection import get_database_url, get_engine

ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "artifacts")
INDEX_PATH = os.path.join(ARTIFACT_DIR, "similarity_index.faiss")
METADATA_PATH = os.path.join(ARTIFACT_DIR, "similarity_metadata.json")

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# IIITs run on a public-private-partnership model; every other institute type
# here (IIT, NIT, GFTI) is centrally or state government run. Same convention
# models/ranker.py already uses for its ownership-preference feature.
OWNERSHIP_BY_TYPE = {"IIIT": "PPP", "IIT": "Government", "NIT": "Government", "GFTI": "Government"}

INSTITUTE_TYPE_EXPANDED = {
    "IIT": "IIT (Indian Institute of Technology)",
    "NIT": "NIT (National Institute of Technology)",
    "IIIT": "IIIT (Indian Institute of Information Technology)",
    "GFTI": "GFTI (Government Funded Technical Institute)",
}

# A college's institute type and NIRF tier are the strongest typological
# signal, but they're a handful of tokens next to a branch list of a dozen
# or more entries - embedded as one blob of text, the branch list would
# drown them out and neighbours would cluster on "offers similar branches"
# almost to the exclusion of "is the same kind/tier of institute". Embedding
# the category fields and the branch list separately and combining them with
# fixed weights keeps both signals meaningfully present in the final vector.
CATEGORY_WEIGHT = 0.65
BRANCH_WEIGHT = 0.35


def load_profile_tables(database_url=None):
    database_url = database_url or get_database_url()
    engine = get_engine(database_url)
    colleges = pd.read_sql("SELECT * FROM colleges", engine)
    reference_metadata = pd.read_sql("SELECT * FROM reference_metadata", engine)
    branches = pd.read_sql(
        """
        SELECT DISTINCT cu.college_id, p.branch_name
        FROM cutoffs cu
        JOIN programs p ON cu.program_id = p.program_id
        WHERE cu.year = (SELECT MAX(year) FROM cutoffs)
        """,
        engine,
    )
    return colleges, reference_metadata, branches


def _fee_level(fees_annual_lakhs):
    """Reference_metadata's fees are a manually curated approximation by
    institute-type tier (see db/reference_metadata.csv), so a coarse level
    is honest here; a precise number would overstate the data's precision.
    """
    if fees_annual_lakhs is None or pd.isna(fees_annual_lakhs):
        return None
    if fees_annual_lakhs <= 1.5:
        return "low fees"
    if fees_annual_lakhs <= 2.0:
        return "moderate fees"
    return "high fees"


def _normalize_branch_name(branch_name):
    """Collapses dual-degree / specialization variants of the same base
    branch (e.g. "Electrical Engineering with M.Tech. in Microelectronics")
    down to the base branch name, so one branch doesn't inflate the profile
    with several near-duplicate entries.
    """
    base = re.split(r"\s+with\s+|\s*\(", branch_name, maxsplit=1, flags=re.IGNORECASE)[0]
    return base.strip(" .")


def build_college_profile(college_row, reference_row, branch_names):
    """Assembles a short factual profile for one college from real database
    fields only, split into a category part (name, institute type, ownership
    derived from institute type, state/city, NIRF rank if published, fee
    tier) and a branches part (deduplicated branch names it currently offers,
    from the latest cutoff year on record). No fabricated descriptive prose.

    Returns (category_text, branch_text) - kept separate so build_index can
    embed and weight them independently instead of one field drowning out
    the others (see CATEGORY_WEIGHT/BRANCH_WEIGHT).
    """
    institute_type = college_row["institute_type"]
    category_parts = [
        college_row["canonical_name"],
        f"{INSTITUTE_TYPE_EXPANDED.get(institute_type, institute_type)} institute",
    ]

    ownership = OWNERSHIP_BY_TYPE.get(institute_type)
    if ownership:
        category_parts.append(f"{ownership}-run institute")

    state = college_row["state"]
    city = None
    if reference_row is not None:
        state = state or reference_row.get("location_state")
        city = reference_row.get("location_city")
    if city and state:
        category_parts.append(f"located in {city}, {state}")
    elif state:
        category_parts.append(f"located in {state}")

    nirf_rank = college_row["nirf_rank_latest"]
    if pd.notna(nirf_rank):
        category_parts.append(f"NIRF rank {int(nirf_rank)}")

    fee_level = _fee_level(reference_row.get("fees_annual_lakhs") if reference_row is not None else None)
    if fee_level:
        category_parts.append(fee_level)

    category_text = ". ".join(category_parts)

    normalized_branches = sorted({_normalize_branch_name(b) for b in branch_names})
    branch_text = ("offers " + ", ".join(normalized_branches)) if normalized_branches else ""

    return category_text, branch_text


def build_all_profiles(database_url=None):
    """Returns (profiles, colleges): profiles is {college_id: (category_text,
    branch_text)} for every college in the colleges table, colleges is the
    raw table (used by build_index for the display metadata that ships
    alongside the vectors).
    """
    colleges, reference_metadata, branches = load_profile_tables(database_url)
    reference_by_id = reference_metadata.set_index("college_id").to_dict("index")
    branches_by_college = branches.groupby("college_id")["branch_name"].apply(list).to_dict()

    profiles = {}
    for row in colleges.itertuples(index=False):
        college_row = row._asdict()
        reference_row = reference_by_id.get(row.college_id)
        branch_names = branches_by_college.get(row.college_id, [])
        profiles[row.college_id] = build_college_profile(college_row, reference_row, branch_names)
    return profiles, colleges


def build_index(database_url=None):
    """Offline step: embeds every college profile with a small sentence-
    transformer, builds a cosine-similarity FAISS index (inner product over
    L2-normalized vectors) and persists it plus a metadata JSON (college_id
    order, display fields, profile text). Rerun via `python -m models.similarity`
    whenever college data changes.
    """
    profiles, colleges = build_all_profiles(database_url)
    college_ids = list(profiles.keys())
    category_texts = [profiles[cid][0] for cid in college_ids]
    branch_texts = [profiles[cid][1] or profiles[cid][0] for cid in college_ids]

    print(f"[similarity] embedding {2 * len(college_ids)} profile fields with {EMBEDDING_MODEL_NAME}...")
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    category_embeddings = model.encode(category_texts, normalize_embeddings=True, show_progress_bar=False)
    branch_embeddings = model.encode(branch_texts, normalize_embeddings=True, show_progress_bar=False)

    combined = CATEGORY_WEIGHT * category_embeddings + BRANCH_WEIGHT * branch_embeddings
    combined = combined / np.linalg.norm(combined, axis=1, keepdims=True)
    embeddings = combined.astype("float32")

    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)

    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    faiss.write_index(index, INDEX_PATH)

    colleges_by_id = colleges.set_index("college_id")
    college_display = {}
    for cid in college_ids:
        row = colleges_by_id.loc[cid]
        college_display[cid] = {
            "college_name": row["canonical_name"],
            "institute_type": row["institute_type"],
            "state": row["state"] if pd.notna(row["state"]) else None,
            "nirf_rank": int(row["nirf_rank_latest"]) if pd.notna(row["nirf_rank_latest"]) else None,
        }

    metadata = {
        "embedding_model": EMBEDDING_MODEL_NAME,
        "category_weight": CATEGORY_WEIGHT,
        "branch_weight": BRANCH_WEIGHT,
        "college_ids": college_ids,
        "colleges": college_display,
        "profiles": {cid: {"category": profiles[cid][0], "branches": profiles[cid][1]} for cid in college_ids},
    }
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"[similarity] index built: {index.ntotal} vectors, dim {embeddings.shape[1]}, saved to {ARTIFACT_DIR}")
    return index, metadata


def load_similarity_index():
    """Loads the persisted FAISS index and metadata once - meant to be called
    at API startup, same pattern as load_ranker()/load_artifacts() elsewhere in
    models/. Returns None if the index hasn't been built yet (run build_index first).
    """
    if not (os.path.exists(INDEX_PATH) and os.path.exists(METADATA_PATH)):
        return None
    index = faiss.read_index(INDEX_PATH)
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    return index, metadata


def get_similar_colleges(college_id, index, metadata, k=5):
    """Top-k nearest neighbours for one college by profile similarity - an
    ordering by shared type, location, ranking, and programs, not a
    personalized match for any particular student. Excludes the query
    college itself. Returns [] if college_id has no indexed profile, rather
    than raising, so a bad or unknown id is handled cleanly by the caller.
    """
    college_ids = metadata["college_ids"]
    if college_id not in college_ids:
        return []

    query_row = college_ids.index(college_id)
    query_vector = index.reconstruct(query_row).reshape(1, -1)

    search_k = min(k + 1, index.ntotal)
    scores, neighbour_rows = index.search(query_vector, search_k)

    results = []
    for score, row in zip(scores[0], neighbour_rows[0]):
        if row < 0:
            continue
        neighbour_id = college_ids[row]
        if neighbour_id == college_id:
            continue
        info = metadata["colleges"][neighbour_id]
        results.append(
            {
                "college_id": neighbour_id,
                "college_name": info["college_name"],
                "institute_type": info["institute_type"],
                "state": info["state"],
                "nirf_rank": info["nirf_rank"],
                "similarity_score": round(float(score), 3),
            }
        )
        if len(results) == k:
            break
    return results


def _demo():
    """Concrete verification: top-5 neighbours for a top IIT, a mid-tier NIT,
    and an IIIT, printed so the results are eyeball-checkable for whether
    they're defensible rather than random.
    """
    bundle = load_similarity_index()
    if bundle is None:
        print("[similarity] no index found, building it first...")
        bundle = build_index()
    index, metadata = bundle

    queries = [
        ("top IIT", "indian-institute-of-technology-bombay"),
        ("mid-tier NIT", "national-institute-of-technology-durgapur"),
        ("IIIT", "indian-institute-of-information-technology-allahabad"),
    ]
    for label, college_id in queries:
        name = metadata["colleges"][college_id]["college_name"]
        print(f"\n=== {label}: {name} ===")
        for neighbour in get_similar_colleges(college_id, index, metadata, k=5):
            print(
                f"    {neighbour['similarity_score']:.3f}  {neighbour['college_name']} "
                f"({neighbour['institute_type']}, {neighbour['state']}, NIRF {neighbour['nirf_rank']})"
            )


if __name__ == "__main__":
    _demo()
