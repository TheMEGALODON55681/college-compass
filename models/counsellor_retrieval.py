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
field, and for a rank or probability also program, category, quota, seat pool
and round) so the generation step can cite it and models/counsellor.py's
grounding validator can verify that every number the model states came from
here, for the college and kind of figure it was attributed to. No prose is
invented in this module - only structured facts.
"""

import re

import pandas as pd
from sqlalchemy import text

from api.eligibility import StudentProfile, get_eligible_colleges
from db.connection import get_database_url, get_engine
from models.admission_probability import predict_admission_probability
from models.ranker import CS_ADJACENT_KEYWORDS, is_cs_adjacent
from models.regressor_dataset import TRAINING_GENDER as GENDER_NEUTRAL

PLACEMENT_KEYWORDS = ["placement", "package", "salary", "ctc", "job offer", "stipend", "internship pay"]
SIMILAR_KEYWORDS = ["similar", " like ", "alternative", "instead of", "options near", "comparable", "other colleges"]

TOP_N_STRUCTURED_BRANCHES = 5
TOP_K_SEMANTIC = 5

# Cap on the named college's cutoff-history rows when the question also asks
# for alternatives ("colleges similar to IIT Delhi"), which puts that history
# in one prompt next to five neighbours. Uncapped, IIT Delhi's 201 rows (before
# the history was limited to Gender-Neutral seats) made a prompt of about 8,477
# tokens and a free-tier provider refused it (8,000 per minute). At 3.4
# characters per token the largest prompt over all colleges (IIT Patna) is
# about 6,620 tokens at 130 rows and 7,014 at 140, so 120 (6,189) keeps every
# college under 7,000 with room for the estimate being off.
MIXED_HISTORY_ROW_CAP = 120

# Matched against the canonical name, not the database's institute_type: four
# IIIT-named colleges (Bhubaneswar, Naya Raipur, Raichur, Senapati Manipur)
# are typed GFTI there, so a lookup by type never gave them a short alias.
_SHORT_NAME_PHRASES = (
    ("iit", "indian institute of technology"),
    ("nit", "national institute of technology"),
    ("iiit", "indian institute of information technology"),
    ("iiit", "international institute of information technology"),
)

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


def _college_aliases(college_id, canonical_name):
    """A college's full canonical name plus a short "{type} {city}" alias
    (e.g. "iit bombay") derived from wherever the institute-type phrase
    appears in the canonical name - not just as a prefix, since several NITs
    are named after a person before "National Institute of Technology"
    (e.g. "Malaviya National Institute of Technology Jaipur"). Students ask
    about "IIT Bombay" or "MNIT Jaipur", not the full canonical name.
    """
    lname = canonical_name.lower()
    aliases = [lname]
    for short, phrase in _SHORT_NAME_PHRASES:
        match = re.search(re.escape(phrase), lname)
        if match:
            remainder = re.sub(r"[^a-z0-9]+", " ", lname[match.end():]).strip()
            if remainder:
                aliases.append(f"{short} {remainder}")
            break
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
        for alias in _college_aliases(row.college_id, row.canonical_name):
            alias_to_college_id[alias] = row.college_id

    return {"colleges": colleges, "branch_names": sorted(set(branch_names)), "alias_to_college_id": alias_to_college_id}


def _match_college(question, lookup):
    """Longest alias match wins, so a short false positive doesn't shadow a
    longer, more specific one (e.g. "iit bombay" over a stray "bombay"). An
    alias only matches as whole words: "iit bhubaneswar" sits inside "iiit
    bhubaneswar" as a plain substring, and must not claim it.
    """
    q = question.lower()
    matches = [
        (len(alias), college_id)
        for alias, college_id in lookup["alias_to_college_id"].items()
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", q)
    ]
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


def _record(college_id, year, field, value, label, **attribution):
    """One number the answer may state, with the row it came from. `field` is
    its kind (actual_closing_rank, predicted_closing_rank, admission_probability,
    nirf_rank, ...). A rank or probability record also carries program_id,
    category, quota, pool and round, which models/counsellor.py checks a stated
    number against; a college-level figure (NIRF rank, fees, similarity score)
    carries none of them.
    """
    return {"college_id": college_id, "year": year, "field": field, "value": value, "label": label, **attribution}


def _historical_closing_ranks(college_id, branch_filter, cs_adjacent_only, database_url=None, max_rows=None):
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
    # Gender-Neutral seats only, the pool the whole product serves: the year is
    # the latest one that has such rows, and a year reported per round keeps its
    # final round, the same settled row /cutoffs shows (get_cutoff_history).
    query = text(
        """
        WITH ranked AS (
            SELECT cu.year, cu.program_id, p.branch_name, cu.category, cu.quota, cu.round, cu.closing_rank,
                   ROW_NUMBER() OVER (
                       PARTITION BY cu.program_id, cu.category
                       ORDER BY (cu.round IS NULL) ASC, cu.round DESC
                   ) AS rn
            FROM cutoffs cu
            JOIN programs p ON cu.program_id = p.program_id
            WHERE cu.college_id = :college_id
              AND cu.quota = :quota
              AND cu.gender_seat_type = :pool
              AND cu.year = (
                  SELECT MAX(year) FROM cutoffs
                  WHERE college_id = :college_id AND quota = :quota AND gender_seat_type = :pool
              )
        )
        SELECT year, program_id, branch_name, category, quota, round, closing_rank FROM ranked WHERE rn = 1
        """
    )
    params = {"college_id": college_id, "pool": GENDER_NEUTRAL}
    history = pd.read_sql(query, engine, params={**params, "quota": "AI"})
    if history.empty:
        history = pd.read_sql(query, engine, params={**params, "quota": "OS"})

    if branch_filter:
        history = history[history["branch_name"].str.contains(re.escape(branch_filter), case=False, na=False)]
    elif cs_adjacent_only:
        history = history[history["branch_name"].apply(is_cs_adjacent)]

    if max_rows is not None:
        # OPEN rows first, so every branch keeps its OPEN row, then a fixed
        # order: the same question always attaches the same rows.
        history = (
            history.assign(not_open=history["category"] != "OPEN")
            .sort_values(["not_open", "branch_name", "category", "closing_rank"])
            .head(max_rows)
        )

    records = []
    for row in history.itertuples(index=False):
        round_ = int(row.round) if pd.notna(row.round) else None
        round_part = f", round {round_}" if round_ is not None else ""
        records.append(
            _record(
                college_id,
                int(row.year),
                "actual_closing_rank",
                int(row.closing_rank),
                f"{row.branch_name} actual JoSAA closing rank {row.year}, quota {row.quota}, category {row.category}{round_part}",
                program_id=row.program_id,
                branch=row.branch_name,
                category=row.category,
                quota=row.quota,
                pool=GENDER_NEUTRAL,
                round=round_,
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
        # The forecast is Gender-Neutral and not tied to a counselling round.
        row = {"program_id": r["program_id"], "branch": r["branch_name"], "category": student.category, "quota": r["quota_used"], "pool": GENDER_NEUTRAL, "round": None}
        records.append(
            _record(
                college_id,
                2025,
                "predicted_closing_rank",
                r["predicted_closing_rank"],
                f"{r['branch_name']} predicted closing rank (2025 forecast, quota {r['quota_used']}, category {student.category})",
                **row,
            )
        )
        records.append(_record(college_id, 2025, "band", r["band"], f"{r['branch_name']} eligibility band: {r['band']}", **row))
        records.append(
            _record(college_id, 2025, "admission_probability", probability, f"{r['branch_name']} calibrated admission probability", **row)
        )
    return records


def _structured_records_for_college(college_id, student, model_state, branch_filter=None, cs_adjacent_only=False, history_row_cap=None):
    """Real numbers for one college: predicted closing rank / band / P(admit)
    per eligible branch if a student profile is given, else the latest
    actual historical closing rank per branch (at most history_row_cap rows
    when given). Always adds NIRF rank and fees if on record.
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
        records = _historical_closing_ranks(college_id, branch_filter, cs_adjacent_only, max_rows=history_row_cap)

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


def _get_embedding_model(model_state):
    """Lazy, cached in model_state exactly like every other artifact in
    api/main.py's lifespan - except this one loads on first call instead of
    at boot, since it's only needed for this one retrieval path and even
    importing onnxruntime/tokenizers has a real cost. The import is
    function-local so that cost is deferred too, not just the InferenceSession
    construction.
    """
    if "embedding_model" not in model_state:
        from models.onnx_encoder import OnnxSentenceEncoder

        model_state["embedding_model"] = OnnxSentenceEncoder()
    return model_state["embedding_model"]


def _semantic_records(question, model_state, exclude_college_ids, student, cs_adjacent_only):
    """Embeds the question at request time (the model loads lazily on first
    use, see _get_embedding_model above) and searches the existing
    similarity index - no second index is built. Attaches structured numbers
    for each matched college too, when a student profile is available, so
    the fuzzy path is just as numerically grounded as the named-college path.
    """
    similarity_bundle = model_state.get("similarity_bundle")
    if similarity_bundle is None:
        return []
    embedding_model = _get_embedding_model(model_state)

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
    """Returns {"mode", "records", "college_ids", "college_aliases",
    "student_inputs"}. college_aliases maps each college in the bundle to the
    names a question or an answer may use for it.

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

    wants_semantic = _wants_semantic(question)
    records = []
    college_ids = []
    if matched_college:
        records.extend(
            _structured_records_for_college(
                matched_college,
                student,
                model_state,
                branch_filter=matched_branch,
                cs_adjacent_only=cs_adjacent_only,
                history_row_cap=MIXED_HISTORY_ROW_CAP if wants_semantic else None,
            )
        )
        college_ids.append(matched_college)

    if not matched_college or wants_semantic:
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

    # The names each college may be called in an answer, so the grounding check
    # can tell which college a sentence is about.
    college_aliases = {cid: [] for cid in college_ids}
    for alias, cid in lookup["alias_to_college_id"].items():
        if cid in college_aliases:
            college_aliases[cid].append(alias)

    return {
        "mode": mode,
        "records": records,
        "college_ids": college_ids,
        "college_aliases": college_aliases,
        "student_inputs": student_inputs,
    }
