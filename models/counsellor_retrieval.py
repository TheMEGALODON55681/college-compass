"""Assembles a grounded context bundle for a student's counsellor question,
from the system's own data only.

Two retrieval paths, tried in order:
- Structured lookup, when the question names a college: reuses the existing
  eligibility filter (api/eligibility.py), the trained cutoff regressor's
  forecast, and the calibrated admission-probability artifacts - exactly the
  same numbers /recommend already serves. No separate model, no
  reimplementation.
- Semantic retrieval, for fuzzy questions that don't name a college ("good CS
  options near my rank", "colleges like X"): embeds the free-text question at
  request time and searches the existing similarity FAISS index
  (models/similarity.py) for the nearest college profiles. No second index.

Every record in the returned bundle carries its own source (college_id, year,
field) so the generation step can cite it and models/counsellor.py's
grounding validator can verify every number the model states actually came
from here. No prose is invented in this module - only structured facts.
"""

import re

import pandas as pd
from sqlalchemy import text

from api.eligibility import StudentProfile, get_eligible_colleges
from db.connection import get_database_url, get_engine
from models.admission_probability import predict_admission_probability
from models.ranker import CS_ADJACENT_KEYWORDS, is_cs_adjacent

PLACEMENT_KEYWORDS = ["placement", "package", "salary", "ctc", "job offer", "stipend", "internship pay"]
SIMILAR_KEYWORDS = ["similar", " like ", "alternative", "instead of", "options near", "comparable", "other colleges"]

TOP_N_STRUCTURED_BRANCHES = 5
TOP_K_SEMANTIC = 5

_INSTITUTE_TYPE_PREFIX = {
    "IIT": "indian institute of technology",
    "NIT": "national institute of technology",
    "IIIT": "indian institute of information technology",
}

# A handful of well-known colloquial nicknames that don't reduce to a clean
# "{type} {city}" alias even after stripping the institute-type prefix (a
# person's name in front, like "Malaviya National Institute of Technology
# Jaipur", still works - see _college_aliases - but a nickname unrelated to
# the city name, like BHU or Trichy, has to be listed by hand). Small and
# bounded on purpose: this is a chat spine, not a full NLP entity matcher.
MANUAL_ALIASES = {
    "indian-institute-of-technology-bhu-varanasi": ["iit bhu", "bhu varanasi"],
    "indian-institute-of-technology-ism-dhanbad": ["iit ism dhanbad", "iit dhanbad", "ism dhanbad"],
    "national-institute-of-technology-tiruchirappalli": ["nit trichy", "nit trichi"],
}


def _college_aliases(college_id, canonical_name, institute_type):
    """A college's full canonical name plus a short "{type} {city}" alias
    (e.g. "iit bombay") derived from wherever the institute-type phrase
    appears in the canonical name - not just as a prefix, since several NITs
    are named after a person before "National Institute of Technology"
    (e.g. "Malaviya National Institute of Technology Jaipur"). Students ask
    about "IIT Bombay" or "MNIT Jaipur", not the full canonical name.
    """
    lname = canonical_name.lower()
    aliases = [lname]
    prefix = _INSTITUTE_TYPE_PREFIX.get(institute_type)
    if prefix:
        match = re.search(re.escape(prefix), lname)
        if match:
            remainder = re.sub(r"[^a-z0-9]+", " ", lname[match.end():]).strip()
            if remainder:
                aliases.append(f"{institute_type.lower()} {remainder}")
    aliases.extend(MANUAL_ALIASES.get(college_id, []))
    return aliases


def build_lookup_cache(database_url=None):
    """Call once at API startup, same pattern as the other model_state
    artifacts - name matching should not re-query the database per question.
    """
    database_url = database_url or get_database_url()
    engine = get_engine(database_url)
    colleges = pd.read_sql("SELECT college_id, canonical_name, institute_type, state, nirf_rank_latest FROM colleges", engine)
    branch_names = pd.read_sql("SELECT DISTINCT branch_name FROM programs", engine)["branch_name"].tolist()

    alias_to_college_id = {}
    for row in colleges.itertuples(index=False):
        for alias in _college_aliases(row.college_id, row.canonical_name, row.institute_type):
            alias_to_college_id[alias] = row.college_id

    return {"colleges": colleges, "branch_names": sorted(set(branch_names)), "alias_to_college_id": alias_to_college_id}


def _match_college(question, lookup):
    """Longest alias match wins, so a short false positive doesn't shadow a
    longer, more specific one (e.g. "iit bombay" over a stray "bombay").
    """
    q = question.lower()
    matches = [(len(alias), college_id) for alias, college_id in lookup["alias_to_college_id"].items() if alias in q]
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def _branch_core(branch_name):
    """The generic topic prefix of a branch name, e.g. "Computer Science" out
    of "Computer Science and Engineering" - students say "computer science",
    not the full official branch name.
    """
    return re.split(r"\s+and\s+|\s+engineering\b", branch_name, maxsplit=1, flags=re.IGNORECASE)[0].strip()


def _match_branch(question, branch_names):
    """Direct containment first (the full branch name appears in the
    question) - if none, falls back to a core-topic match (e.g. "computer
    science" matching "Computer Science and Engineering"), preferring the
    shortest/most generic branch name among core matches so a plain "computer
    science" question doesn't get matched to a specialization variant like
    "...(Artificial Intelligence & Data Science)".
    """
    q = question.lower()
    direct = [b for b in branch_names if b.lower() in q]
    if direct:
        return max(direct, key=len)

    core_matches = [b for b in branch_names if _branch_core(b).lower() in q]
    return min(core_matches, key=len) if core_matches else None


def _wants_cs_adjacent(question):
    q = question.lower()
    return any(kw in q for kw in CS_ADJACENT_KEYWORDS)


def is_placement_question(question):
    q = question.lower()
    return any(kw in q for kw in PLACEMENT_KEYWORDS)


def _wants_semantic(question):
    q = question.lower()
    return any(kw in q for kw in SIMILAR_KEYWORDS)


def _record(college_id, year, field, value, label):
    return {"college_id": college_id, "year": year, "field": field, "value": value, "label": label}


def _historical_closing_ranks(college_id, branch_filter, cs_adjacent_only, database_url=None):
    """No student profile given, so there's no eligibility/forecast to run -
    falls back to the real, most recent actual JoSAA closing rank per branch,
    straight from the cutoffs table, clearly labeled as historical rather
    than predicted.

    Quota AI (All India) is preferred since it's the quota every student
    competes under regardless of home state, but not every college has any
    AI-quota seats at all - several NITs (e.g. MNIT Jaipur) allocate purely
    through Home State / Other State quotas. Falls back to OS (Other State)
    in that case, since that's the quota any non-home-state student would
    actually face; the label always names the real quota used, never assumes AI.
    """
    database_url = database_url or get_database_url()
    engine = get_engine(database_url)
    query = text(
        """
        SELECT cu.year, p.branch_name, cu.category, cu.quota, cu.closing_rank
        FROM cutoffs cu
        JOIN programs p ON cu.program_id = p.program_id
        WHERE cu.college_id = :college_id
          AND cu.quota = :quota
          AND cu.year = (SELECT MAX(year) FROM cutoffs WHERE college_id = :college_id AND quota = :quota)
        """
    )
    history = pd.read_sql(query, engine, params={"college_id": college_id, "quota": "AI"})
    if history.empty:
        history = pd.read_sql(query, engine, params={"college_id": college_id, "quota": "OS"})

    if branch_filter:
        history = history[history["branch_name"].str.contains(re.escape(branch_filter), case=False, na=False)]
    elif cs_adjacent_only:
        history = history[history["branch_name"].apply(is_cs_adjacent)]

    records = []
    for row in history.itertuples(index=False):
        records.append(
            _record(
                college_id,
                int(row.year),
                "actual_closing_rank",
                int(row.closing_rank),
                f"{row.branch_name} actual JoSAA closing rank {row.year}, quota {row.quota}, category {row.category}",
            )
        )
    return records


def _forecast_records(college_id, student, forecasts, reference_tables, probability_artifacts, branch_filter, cs_adjacent_only):
    """A student profile is given, so this reuses the exact /recommend path:
    the eligibility filter over the trained regressor's forecast, then the
    calibrated admission-probability artifacts for each eligible branch at
    this college.
    """
    eligible = get_eligible_colleges(student, forecasts=forecasts, reference_tables=reference_tables)
    rows = [r for r in eligible if r["college_id"] == college_id]
    if branch_filter:
        rows = [r for r in rows if branch_filter.lower() in r["branch_name"].lower()]
    elif cs_adjacent_only:
        rows = [r for r in rows if is_cs_adjacent(r["branch_name"])]

    records = []
    for r in rows[:TOP_N_STRUCTURED_BRANCHES]:
        has_lag = r["prediction_source"] == "delta_model"
        probability = predict_admission_probability(r["predicted_closing_rank"], student.jee_rank, has_lag, probability_artifacts)
        records.append(
            _record(
                college_id,
                2025,
                "predicted_closing_rank",
                r["predicted_closing_rank"],
                f"{r['branch_name']} predicted closing rank (2025 forecast, quota {r['quota_used']}, category {student.category})",
            )
        )
        records.append(_record(college_id, 2025, "band", r["band"], f"{r['branch_name']} eligibility band: {r['band']}"))
        records.append(
            _record(college_id, 2025, "admission_probability", probability, f"{r['branch_name']} calibrated admission probability")
        )
    return records


def _structured_records_for_college(college_id, student, model_state, branch_filter=None, cs_adjacent_only=False):
    """Real numbers for one college: predicted closing rank / band / P(admit)
    per eligible branch if a student profile is given, else the latest
    actual historical closing rank per branch. Always adds NIRF rank and
    fees if on record.
    """
    if student is not None:
        records = _forecast_records(
            college_id,
            student,
            model_state["merged_forecasts"],
            model_state["reference_tables"],
            model_state["probability_artifacts"],
            branch_filter,
            cs_adjacent_only,
        )
    else:
        records = _historical_closing_ranks(college_id, branch_filter, cs_adjacent_only)

    colleges, _programs, reference_metadata = model_state["reference_tables"]
    college_row = colleges[colleges["college_id"] == college_id]
    if not college_row.empty and pd.notna(college_row.iloc[0]["nirf_rank_latest"]):
        records.append(_record(college_id, None, "nirf_rank", int(college_row.iloc[0]["nirf_rank_latest"]), "latest NIRF rank"))

    fee_row = reference_metadata[reference_metadata["college_id"] == college_id]
    if not fee_row.empty and pd.notna(fee_row.iloc[0]["fees_annual_lakhs"]):
        records.append(
            _record(college_id, None, "fees_annual_lakhs", float(fee_row.iloc[0]["fees_annual_lakhs"]), "approximate annual fees (lakhs), by institute-type tier")
        )
    return records


def _semantic_records(question, model_state, exclude_college_ids, student, cs_adjacent_only):
    """Embeds the question at request time (the model is loaded once at API
    startup, see api/main.py) and searches the existing similarity index -
    no second index is built. Attaches structured numbers for each matched
    college too, when a student profile is available, so the fuzzy path is
    just as numerically grounded as the named-college path.
    """
    similarity_bundle = model_state.get("similarity_bundle")
    embedding_model = model_state.get("embedding_model")
    if similarity_bundle is None or embedding_model is None:
        return []

    index, metadata = similarity_bundle
    query_vector = embedding_model.encode([question], normalize_embeddings=True).astype("float32")
    scores, rows = index.search(query_vector, TOP_K_SEMANTIC)

    records = []
    for score, row in zip(scores[0], rows[0]):
        if row < 0:
            continue
        college_id = metadata["college_ids"][row]
        if college_id in exclude_college_ids:
            continue
        info = metadata["colleges"][college_id]
        records.append(
            _record(
                college_id,
                None,
                "semantic_match",
                round(float(score), 3),
                f"{info['college_name']} ({info['institute_type']}) matched by profile similarity to the question",
            )
        )
        if student is not None:
            records.extend(_structured_records_for_college(college_id, student, model_state, cs_adjacent_only=cs_adjacent_only))
    return records


def build_context_bundle(question, student_profile_dict, model_state):
    """Returns {"mode", "records", "college_ids", "student_inputs"}.

    mode is one of "structured" (a college was named), "semantic" (no
    college named, matched by free-text similarity), "mixed" (a college was
    named but the question also asked for alternatives), "out_of_scope_placement",
    or "no_match". student_inputs carries the numbers the student themselves
    provided (rank, budget) so the grounding validator does not flag a
    restated student input as a fabricated system number.
    """
    if is_placement_question(question):
        return {"mode": "out_of_scope_placement", "records": [], "college_ids": [], "student_inputs": {}}

    lookup = model_state["counsellor_lookup"]
    student = StudentProfile(**student_profile_dict) if student_profile_dict else None
    student_inputs = {}
    if student_profile_dict:
        if student_profile_dict.get("jee_rank") is not None:
            student_inputs["jee_rank"] = student_profile_dict["jee_rank"]
        if student_profile_dict.get("budget_annual_lakhs") is not None:
            student_inputs["budget_annual_lakhs"] = student_profile_dict["budget_annual_lakhs"]

    matched_college = _match_college(question, lookup)
    matched_branch = _match_branch(question, lookup["branch_names"])
    cs_adjacent_only = matched_branch is None and _wants_cs_adjacent(question)

    records = []
    college_ids = []
    if matched_college:
        records.extend(
            _structured_records_for_college(
                matched_college, student, model_state, branch_filter=matched_branch, cs_adjacent_only=cs_adjacent_only
            )
        )
        college_ids.append(matched_college)

    if not matched_college or _wants_semantic(question):
        semantic_records = _semantic_records(
            question, model_state, exclude_college_ids=set(college_ids), student=student, cs_adjacent_only=cs_adjacent_only
        )
        for r in semantic_records:
            if r["college_id"] not in college_ids:
                college_ids.append(r["college_id"])
        records.extend(semantic_records)
        mode = "semantic" if not matched_college else "mixed"
    else:
        mode = "structured"

    if not records:
        return {"mode": "no_match", "records": [], "college_ids": [], "student_inputs": student_inputs}

    return {"mode": mode, "records": records, "college_ids": college_ids, "student_inputs": student_inputs}
