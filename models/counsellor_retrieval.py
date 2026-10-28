"""Assembles a grounded context bundle for a student's counsellor question,
from the system's own data only.

Two retrieval paths, tried in order:
- Structured lookup, when the question names a college: reuses the existing
  eligibility filter (api/eligibility.py), the trained cutoff regressor's
  forecast, and the calibrated admission-probability artifacts - exactly the
  same numbers /recommend already serves. No separate model, no
  reimplementation. The named college also carries its real closing ranks,
  since a student out of reach of a branch has no forecast row for it.
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
SIMILAR_KEYWORDS = ["similar", "alternative", "instead of", "options near", "comparable", "other colleges"]
# "colleges like IIT Delhi", not "I'd like to know" or "I would like a list".
LIKE_AS_COMPARISON = re.compile(r"(?<!['’]d)(?<!would)\s+like\s+(?!to\b|a\b|an\b|some\b)")

TOP_N_STRUCTURED_BRANCHES = 5
TOP_K_SEMANTIC = 5

# Caps on the named college's cutoff-history rows, so the prompt stays under the
# free-tier provider's limit (8,000 tokens a minute; the repo's line is 7,000).
# Each row's label carries branch, program, category, seat pool and round, and the
# line carries the college and year. Measured at 3.4 characters per token over
# every college, 16 profiles and two phrasings (full name, shortest alias), real
# neighbours, with the category-aware order below:
# - Alongside alternatives ("colleges similar to IIT Delhi", five neighbours whose
#   forecast rows share the prompt): worst prompt 8,036 tokens at 90 rows (11 of
#   4,256 over 7,000), 7,097 at 70, 6,623 at 60. No college has more than 32 OPEN
#   rows, so every branch keeps its OPEN row.
# - With a student profile (the named college's forecast rows share the prompt):
#   6,257 at 90 rows (IIT Patna).
# - No profile, one college: 6,953 at 120 rows and 6,025 at 100 (IIT Patna, 149
#   rows). IIT Delhi has 112 rows and keeps them all.
ALTERNATIVES_HISTORY_ROW_CAP = 60
SHARED_HISTORY_ROW_CAP = 90
SOLO_HISTORY_ROW_CAP = 112

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


_CATEGORY_WORDS = (("open", "OPEN"), ("ews", "EWS"), ("obc", "OBC-NCL"), ("sc", "SC"), ("st", "ST"))


def _categories_in(question):
    """The reserved categories a question names, in the API's vocabulary, so a
    capped history keeps their rows when there is no student profile to say.
    """
    q = question.lower()
    return frozenset(api for word, api in _CATEGORY_WORDS if re.search(rf"(?<![a-z0-9]){word}(?![a-z0-9])", q))


def _wants_cs_adjacent(question):
    q = question.lower()
    return any(kw in q for kw in CS_ADJACENT_KEYWORDS)


def is_placement_question(question):
    q = question.lower()
    return any(kw in q for kw in PLACEMENT_KEYWORDS)


def _wants_semantic(question):
    q = question.lower()
    return any(kw in q for kw in SIMILAR_KEYWORDS) or bool(LIKE_AS_COMPARISON.search(q))


_DURATION_WORDS = {4: "four-year", 5: "five-year"}


def _program_tag(degree_type, duration_years):
    """The program a branch row belongs to, so IIT Delhi's 4-year B.Tech and its
    5-year dual degree, which share the branch name "Computer Science and
    Engineering", read differently. No digits and no full stops: the grounding
    check reads every digit group in an answer as a figure, and a full stop
    inside a label ("B. Tech.") would split the model's sentence.
    """
    lowered = degree_type.lower()
    if "dual" in lowered:
        kind = "dual degree"
    elif "integrated" in lowered:
        kind = "integrated"
    elif degree_type == "Bachelor of Technology":
        kind = "BTech"
    else:
        kind = degree_type.replace(".", "")
    return f"{_DURATION_WORDS.get(duration_years, f'{duration_years}-year')} {kind}"


def _admission_label(what, branch, program, category, round_, quota=None):
    """What the model reads beside an admission figure: branch with its program,
    category, seat pool and round. The line it sits on starts with the college
    and the year (models/counsellor._format_context), so the six fields are
    all on the line; repeating the year here would cost a few thousand tokens
    over a long history. A year with no round breakdown, and the forecast, say
    so instead of leaving the round out.
    """
    round_part = f"round {round_}" if round_ is not None else "no round data"
    quota_part = f", quota {quota}" if quota else ""
    return f"{branch} ({program}) {what}, {category}, {GENDER_NEUTRAL}, {round_part}{quota_part}"


def _record(college_id, year, field, value, label, **attribution):
    """One number the answer may state, with the row it came from. `field` is
    its kind (actual_closing_rank, predicted_closing_rank, admission_probability,
    nirf_rank, ...). A rank or probability record also carries program_id,
    category, quota, pool and round, which models/counsellor.py checks a stated
    number against; a college-level figure (NIRF rank, fees, similarity score)
    carries none of them.
    """
    return {"college_id": college_id, "year": year, "field": field, "value": value, "label": label, **attribution}


def _historical_closing_ranks(college_id, branch_filter, cs_adjacent_only, database_url=None, max_rows=None, categories=()):
    """The real, most recent actual JoSAA closing rank per branch, straight
    from the cutoffs table, clearly labeled as historical rather than
    predicted. Used when there is no student profile (no eligibility or
    forecast to run) and, beside the forecast rows, for a college the question
    names.

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
            SELECT cu.year, cu.program_id, p.branch_name, p.degree_type, p.duration_years, cu.category, cu.quota, cu.round, cu.closing_rank,
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
        SELECT year, program_id, branch_name, degree_type, duration_years, category, quota, round, closing_rank FROM ranked WHERE rn = 1
        """
    )
    params = {"college_id": college_id, "pool": GENDER_NEUTRAL}
    history = pd.read_sql(query, engine, params={**params, "quota": "AI"})
    if history.empty:
        history = pd.read_sql(query, engine, params={**params, "quota": "OS"})
    if history.empty:
        # Four colleges have only pre-2018 data, so no Gender-Neutral row. The
        # branch filters and the sort below need the columns a row set has.
        return []

    if branch_filter:
        history = history[history["branch_name"].str.contains(re.escape(branch_filter), case=False, na=False)]
    elif cs_adjacent_only:
        history = history[history["branch_name"].apply(is_cs_adjacent)]

    if max_rows is not None:
        # OPEN rows and the categories the student or the question names first,
        # so every branch keeps the rows that can be used (OPEN plus one
        # category is at most 64 rows at any college; the alternatives cap of 60
        # can leave out IIT Patna's last branches for OBC-NCL or SC), then a fixed
        # order: the same question always attaches the same rows.
        wanted = history["category"].isin({"OPEN", *categories})
        history = history.assign(not_wanted=~wanted).sort_values(["not_wanted", "branch_name", "category", "closing_rank"]).head(max_rows)

    records = []
    for row in history.itertuples(index=False):
        round_ = int(row.round) if pd.notna(row.round) else None
        program = _program_tag(row.degree_type, row.duration_years)
        records.append(
            _record(
                college_id,
                int(row.year),
                "actual_closing_rank",
                int(row.closing_rank),
                _admission_label("closing rank", row.branch_name, program, row.category, round_, row.quota),
                program_id=row.program_id,
                program=program,
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

    programs = reference_tables[1].set_index("program_id")
    records = []
    for r in rows[:TOP_N_STRUCTURED_BRANCHES]:
        has_lag = r["prediction_source"] == "delta_model"
        probability = predict_admission_probability(r["predicted_closing_rank"], student.jee_rank, has_lag, probability_artifacts)
        program = _program_tag(programs.at[r["program_id"], "degree_type"], int(programs.at[r["program_id"], "duration_years"]))
        # The forecast is Gender-Neutral and not tied to a counselling round.
        row = {
            "program_id": r["program_id"],
            "program": program,
            "branch": r["branch_name"],
            "category": student.category,
            "quota": r["quota_used"],
            "pool": GENDER_NEUTRAL,
            "round": None,
        }

        def label(what, quota=None):
            return _admission_label(what, r["branch_name"], program, student.category, None, quota)

        records.append(_record(college_id, 2025, "predicted_closing_rank", r["predicted_closing_rank"], label("forecast closing rank", r["quota_used"]), **row))
        records.append(_record(college_id, 2025, "band", r["band"], label("eligibility band"), **row))
        records.append(_record(college_id, 2025, "admission_probability", probability, label("calibrated admission probability"), **row))
    return records


def _structured_records_for_college(
    college_id,
    student,
    model_state,
    branch_filter=None,
    cs_adjacent_only=False,
    history_row_cap=None,
    named=False,
    alongside_alternatives=False,
    question_categories=frozenset(),
):
    """Real numbers for one college: predicted closing rank / band / P(admit)
    per eligible branch if a student profile is given, plus the latest actual
    historical closing rank per branch (at most history_row_cap rows when
    given) when there is no profile or the question names this college. Always
    adds NIRF rank and fees if on record.

    Eligibility lists only the branches a student can reach, so a student out of
    reach of the branch they asked about gets no forecast row for it, and a
    branch the question does not name precisely ("CSE") cannot be told from the
    reachable ones. A named college therefore carries its history beside the
    forecast rows. Next to five alternatives (`alongside_alternatives`) the
    prompt has no room for both, so a student who can reach the college gets
    the forecast only. A college listed as an alternative is not named: it
    stays limited to what the student can reach.
    """
    forecast = []
    if student is not None:
        forecast = _forecast_records(
            college_id,
            student,
            model_state["merged_forecasts"],
            model_state["reference_tables"],
            model_state["probability_artifacts"],
            branch_filter,
            cs_adjacent_only,
        )
    records = forecast
    if student is None or (named and not (alongside_alternatives and forecast)):
        wanted = {student.category} if student else set()
        records = _historical_closing_ranks(college_id, branch_filter, cs_adjacent_only, max_rows=history_row_cap, categories=wanted | question_categories) + forecast

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
    "college_names", "focus", "student_inputs"}. college_aliases maps each
    college in the bundle to the names a question or an answer may use for it;
    college_names to its canonical name. focus is what the question itself named,
    for a verification note to fall back on when an answer's sentence leaves it
    out: the college, a branch a record of that college holds, and the category
    (the one the question names, else the student's).

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
    question_categories = _categories_in(question)

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
                history_row_cap=ALTERNATIVES_HISTORY_ROW_CAP if wants_semantic else SHARED_HISTORY_ROW_CAP if student is not None else SOLO_HISTORY_ROW_CAP,
                named=True,
                alongside_alternatives=wants_semantic,
                question_categories=question_categories,
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

    canonical_names = dict(zip(lookup["colleges"]["college_id"], lookup["colleges"]["canonical_name"]))
    # matched_branch is a substring filter ("Computer Science"); a note needs a
    # branch a record of the named college holds. The shortest one that contains
    # it, as _match_branch picks (a neighbour's own "Computer Science" must not win).
    focus_branch = min(
        (r["branch"] for r in records if r["college_id"] == matched_college and matched_branch and r.get("branch") and matched_branch.lower() in r["branch"].lower()),
        key=lambda b: (len(b), b),
        default=None,
    )
    # The category the question names wins over the profile's; with two named, the profile's.
    focus_category = next(iter(question_categories)) if len(question_categories) == 1 else student.category if student else None
    return {
        "mode": mode,
        "records": records,
        "college_ids": college_ids,
        "college_aliases": college_aliases,
        "college_names": {cid: canonical_names.get(cid, cid) for cid in college_ids},
        # What the question itself named, for a verification note to fall back on
        # when the answer's own sentence leaves the college, branch or category out.
        "focus": {"college_id": matched_college, "branch": focus_branch, "category": focus_category},
        "student_inputs": student_inputs,
    }
