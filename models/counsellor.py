"""Grounded generation: turns a context bundle (see
models/counsellor_retrieval.py) into a natural-language answer through a
provider-agnostic OpenAI-compatible chat endpoint, then enforces numeric
grounding in code before the answer is ever returned.

The system prompt below asks the model to only use the provided context and
never state an unlisted number - but that is a request, not a guarantee, so
this module does not trust it. validate_grounding re-extracts every
rank-like/probability-like number from the model's own answer and checks it
against the bundle's real values with an exact string match (no "close
enough"). Anything that doesn't match gets one regeneration attempt with a
stricter instruction; if it still doesn't match, the ungrounded figure is
stripped from the answer rather than shown, and blocked_ungrounded_figure is
set so the caller can log/surface the event.
"""

import os
import re

from openai import APIStatusError, OpenAI

DEFAULT_LLM_ENDPOINT = "http://localhost:11434/v1"
DEFAULT_LLM_MODEL = "local-model"

PLACEMENT_DECLINE_ANSWER = (
    "This system deliberately does not include placement or package data. "
    "I can help with JEE Main / JoSAA eligibility, predicted cutoffs, admission probability, "
    "and comparing colleges instead."
)

LLM_UNREACHABLE_ANSWER = (
    "The counsellor's language model is not reachable right now, so I can't generate an answer. "
    "Check that LLM_ENDPOINT points at a running OpenAI-compatible server and try again."
)

PROVIDER_REJECTED_ANSWER = (
    "I couldn't answer that. The language model service behind the counsellor refused this request: "
    "it was too long, or the service hit its usage limit. "
    "Wait a minute and ask again, or ask about one college and one branch."
)

SYSTEM_PROMPT = """You are a counsellor for JEE Main / JoSAA admissions into IITs, NITs, IIITs, and GFTIs.

Rules:
- Answer only using the context records given to you. Every rank, cutoff, probability, or fee you state must come from those records, verbatim.
- Never state a number that is not present in the context. If the context does not have the figure the student asked for, say so plainly and suggest what they could ask instead (a specific college name, or their rank and category).
- When you cite a number, name the college_id it came from.
- When you cite a rank, give its branch and program, category, year and round as the context line shows them, so two rows of one branch can be told apart.
- Stay within JoSAA/JEE Main scope for IITs, NITs, IIITs, and GFTIs. Never answer placement, package, or salary questions - state plainly that this system deliberately does not include that data.
- Do not answer general-knowledge questions outside JoSAA admissions.
"""

NUMBER_PATTERN = re.compile(r"-?\d+(?:,\d+)*(?:\.\d+)?%?")

# "1. Check your rank", "2) Compare", "**3.** Decide": a list ordinal is
# formatting, not a figure the system could have stated, so it is never
# checked against the bundle. Two digits at most and a line start keep a
# real figure from hiding here.
LIST_MARKER_PATTERN = re.compile(r"^[ \t]*\*{0,2}(\d{1,2})[.)]\*{0,2}(?=\s)", re.MULTILINE)


def _client():
    endpoint = os.environ.get("LLM_ENDPOINT") or DEFAULT_LLM_ENDPOINT
    api_key = os.environ.get("LLM_API_KEY") or "not-needed"
    return OpenAI(base_url=endpoint, api_key=api_key)


def _completion_text(response):
    """The reply, or ValueError when the model gave nothing (None, empty or blank)."""
    text = response.choices[0].message.content
    if not (text or "").strip():
        raise ValueError("the provider returned an empty completion")
    return text


def _format_context(bundle):
    if not bundle["records"]:
        return "No matching data found in the system for this question."
    lines = []
    for r in bundle["records"]:
        year_part = f", {r['year']}" if r.get("year") else ""
        lines.append(f"- [{r['college_id']}{year_part}] {r['label']}: {r['value']}")
    return "\n".join(lines)


def extract_numbers(text_):
    """Every rank-like or probability-like number in a piece of text, as
    (value, start, end): the value normalized (commas stripped) so it can be
    compared against the bundle's own grounded values, and the span of the
    number as written, so a caller can replace exactly that occurrence.
    """
    list_markers = {m.start(1) for m in LIST_MARKER_PATTERN.finditer(text_)}
    found = []
    for match in NUMBER_PATTERN.finditer(text_):
        if match.start() not in list_markers:
            found.append((match.group().replace(",", ""), match.start(), match.end()))
    return found


def _value_forms(value):
    """Every way a record's value may be written in an answer, normalized the
    same way as extract_numbers: a probability or similarity score between 0
    and 1 also reads as a whole percent ("0.85" as "85" and "85%").
    """
    forms = set()
    if isinstance(value, bool):
        pass
    elif isinstance(value, int):
        forms.add(str(value))
    elif isinstance(value, float):
        forms.add(str(value))
        forms.add(f"{value:.4f}".rstrip("0").rstrip("."))
        if 0 <= value <= 1:
            pct = round(value * 100)
            forms.add(str(pct))
            forms.add(f"{pct}%")
    return forms


def _input_value_strings(bundle):
    """The student's own stated inputs (their rank or budget, echoed back, is
    not a fabricated system number).
    """
    inputs = set()
    for value in bundle.get("student_inputs", {}).values():
        inputs.add(str(value))
        if isinstance(value, float):
            inputs.add(f"{value:.4f}".rstrip("0").rstrip("."))
    return inputs


def _grounded_value_strings(bundle):
    """Every numeric value the bundle actually contains, plus each record's
    own year (a legitimate, sourced number - "the 2025 forecast" - not a
    fabricated figure) and the student's own stated inputs. A flat set: it
    says a number exists somewhere in the bundle, not whose it is, so it is the
    first gate of _ungrounded_spans and not the whole check.
    """
    grounded = set()
    for r in bundle["records"]:
        grounded |= _value_forms(r["value"])
        if r.get("year"):
            grounded.add(str(r["year"]))
    return grounded | _input_value_strings(bundle)


# Attribution. A number is judged against the records of the college, kind,
# year, category, seat pool and round the answer attaches it to. The answer is
# cut into segments (a line or a sentence), and what a segment says about those
# applies to the numbers inside it. Attribution that a segment does not state is
# not checked: with no college named, the number may come from any college the
# bundle covers; with no cue word beside it, it may be any kind of value. That
# is the fallback, and it is the old flat check restricted to the bundle's
# records. A segment is judged as a set, so two categories in one sentence
# ("OPEN 116, OBC-NCL 224") can swap their numbers unnoticed.
SEGMENT_BREAK = re.compile(r"\n+|;\s*|(?<=[.!?])\s+(?=[A-Z\[(*])")
YEAR_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
ROUND_PATTERN = re.compile(r"\bround\s*#?(\d+)", re.IGNORECASE)
# The API's category vocabulary (OPEN, never "General"), with its PwD compound.
CATEGORY_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:OPEN|EWS|OBC-NCL|SC|ST)(?: \(PwD\))?(?![A-Za-z0-9])")
POOL_PATTERN = re.compile(r"\b(female|women)\b|gender[- ]neutral", re.IGNORECASE)

RANK_FIELDS = {"predicted_closing_rank", "actual_closing_rank", "closing_rank"}
# A cue word beside a number says which record fields it can be. A quota is not
# read from the text: "AI" is also a branch name.
KIND_CUES = (
    (re.compile(r"nirf", re.IGNORECASE), {"nirf_rank"}),
    (re.compile(r"\bfees?\b|lakh|tuition", re.IGNORECASE), {"fees_annual_lakhs"}),
    (re.compile(r"probab|chance|likelihood", re.IGNORECASE), {"admission_probability"}),
    (re.compile(r"closing|cut-?off", re.IGNORECASE), RANK_FIELDS),
    (re.compile(r"similarity|score", re.IGNORECASE), {"semantic_match"}),
)
CUE_WINDOW = 60
# The labels spell a program's duration out ("four-year BTech") because a digit
# there would read as a figure, and a model rewrites it as "4-year". A length
# beside a program word names a program: its digit is not a figure, and the
# figure near it must belong to a program of that length. "The last 5 years" or
# "a 5-year trend" has no program word and stays a figure. Matching is ASCII
# only ("f" + dotless i + "ve" must not read as "five") and a mention never
# reaches across a line break.
PROGRAM_DURATIONS = {"four-year": "4", "five-year": "5"}
_LENGTH_WORDS = {"four": "4", "five": "5"}
_DASHES = "".join(chr(c) for c in range(0x2010, 0x2016))
_BLANK = r"[^\S\r\n]"
_LENGTH = rf"(?<![a-z0-9])(four|4|five|5)(?:{_BLANK}|[\-{_DASHES}])*(?:years?|yrs?)(?![a-z])"
_PROGRAM = (
    rf"(?:b\.?{_BLANK}?tech\.?|b\.?{_BLANK}?arch\.?|bachelor(?:{_BLANK}+of{_BLANK}+[a-z]+)?"
    rf"|master(?:{_BLANK}+of{_BLANK}+[a-z]+)?|dual(?:{_BLANK}+degree)?|integrated)"
)
_FLAGS = re.IGNORECASE | re.ASCII
PROGRAM_MENTIONS = (
    # "four-year BTech", "4-yr B.Tech.", "**4-year** BTech", "4-year-BTech", "5-year program"
    re.compile(_LENGTH + rf"(?:{_BLANK}|[|*\-{_DASHES}])+(?:{_PROGRAM}|degree|program)", _FLAGS),
    # "BTech (4 years)", "B.Tech (4-year):", "| BTech | 4 years |"
    re.compile(rf"(?<![a-z]){_PROGRAM}(?:{_BLANK}|[(,:|*\-{_DASHES}])*" + _LENGTH, _FLAGS),
)
# "B.Tech. Computer Science": the full stop ends the abbreviation, not the sentence.
_ABBREVIATION_STOP = re.compile(rf"(?<![a-z])b\.?{_BLANK}?(?:tech|arch)\.", _FLAGS)


def _program_duration(program):
    """The duration digit of a record's program tag ("four-year BTech" -> "4"), or None."""
    return next((d for word, d in PROGRAM_DURATIONS.items() if str(program).startswith(word)), None)


def _program_lengths(text_):
    """(start, digit) of each length in text_ that names a program, as the digit
    ("four" and "4" both read "4").
    """
    return [
        (m.start(1), _LENGTH_WORDS.get(m.group(1).lower(), m.group(1)))
        for pattern in PROGRAM_MENTIONS
        for m in pattern.finditer(text_)
    ]


def _protected_spans(text_, branches, names):
    """Where a branch name or a college name that holds full stops ("B. Tech.
    (CSE) and M.Tech in CSE", "Dr. B R Ambedkar National Institute of
    Technology") is written in full. The sentence splitter must not cut inside
    one, or the figure after it lands in a segment that names no branch or
    college.
    """
    terms = {b for b in branches if "." in b} | {a for aliases in names.values() for a in aliases if "." in a}
    spans = [m.span() for term in terms for m in re.finditer(re.escape(term), text_, re.IGNORECASE)]
    spans += [m.span() for pattern in PROGRAM_MENTIONS for m in pattern.finditer(text_)]
    # "B.Tech. Computer Science": a full stop followed by a branch name ends the
    # abbreviation, so the space after it is not a break. Followed by anything
    # else it ends the sentence.
    for m in _ABBREVIATION_STOP.finditer(text_):
        rest = text_[m.end() :]
        if rest[:1] == " " and any(rest[1:].lower().startswith(b.lower()) for b in branches):
            spans.append((m.start(), m.end() + 1))
    return spans


def _segments(text_, protected=()):
    spans, begin = [], 0
    for match in SEGMENT_BREAK.finditer(text_):
        if any(s <= match.start() < e for s, e in protected):
            continue
        spans.append((begin, match.start()))
        begin = match.end()
    spans.append((begin, len(text_)))
    return spans


def _college_names(bundle):
    """Lowercase names each bundle college may be called in an answer: its id
    (the system prompt asks the model to cite it), the id read as words, and the
    aliases build_context_bundle attached ("iit delhi").
    """
    given = bundle.get("college_aliases", {})
    ids = {r["college_id"] for r in bundle["records"]}
    return {cid: {cid.lower(), cid.lower().replace("-", " "), *given.get(cid, [])} for cid in ids}


def _branches_named(lowered, branches):
    """The branches a segment names by their full name, as whole words. A name
    that only occurs inside a longer branch's name ("Chemical Engineering" in
    "Biotechnology and Biochemical Engineering", "Computer Science and
    Engineering" in "... (Artificial Intelligence)") is not a mention of the
    short branch.
    """
    found = [
        (m.start(), m.end(), b)
        for b in branches
        if b.lower() in lowered
        for m in re.finditer(rf"(?<![a-z0-9]){re.escape(b.lower())}(?![a-z0-9])", lowered)
    ]
    return {b for s, e, b in found if not any(s2 <= s and e <= e2 and e2 - s2 > e - s for s2, e2, _ in found)}


def _segment_context(segment, names, record_years, branches):
    lowered = segment.lower()
    mentioned = {
        cid
        for cid, aliases in names.items()
        if any(re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lowered) for alias in aliases)
    }
    # A college's own name can hold a branch name ("Indian Institute of
    # Information Technology Bhopal"): blank it out before reading branches.
    without_colleges = lowered
    for alias in sorted({a for aliases in names.values() for a in aliases}, key=len, reverse=True):
        without_colleges = re.sub(
            rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lambda m: " " * len(m.group()), without_colleges
        )
    return {
        "colleges": mentioned or set(names),
        "years": {y for y in YEAR_PATTERN.findall(segment) if y in record_years},
        # Only a branch's full name as the records write it; "CSE" is not read.
        "branches": _branches_named(without_colleges, branches),
        "durations": {d for _, d in _program_lengths(segment)},
        "categories": set(CATEGORY_PATTERN.findall(segment)),
        "pools": {"female" if m.group(1) else "gender" for m in POOL_PATTERN.finditer(segment)},
        "rounds": {m.group(1) for m in ROUND_PATTERN.finditer(segment)},
    }


def _kinds_for(answer_text, lo, start, end, hi):
    """The record fields the number at answer_text[start:end] can be, from the
    nearest cue word before it (back to lo) or, failing that, after it (up to
    hi, which the caller sets to `end` when another figure follows, since a cue
    ahead of that figure belongs to it). None when nothing beside the number says.
    """
    # A table cell is its own stretch: a cue in the neighbouring cell ("no NIRF
    # rank" beside a fee) belongs to that cell's figure.
    left = answer_text[max(lo, start - CUE_WINDOW) : start].rsplit("|", 1)[-1]
    right = answer_text[end : min(hi, end + CUE_WINDOW)].split("|", 1)[0]
    for window, nearness in ((left, lambda m: m.end()), (right, lambda m: -m.start())):
        cues = [(nearness(m), fields) for pattern, fields in KIND_CUES for m in pattern.finditer(window)]
        if cues:
            return max(cues, key=lambda cue: cue[0])[1]
    return None


def _agrees(record, context):
    """False when the segment states a year, branch, program duration, category, seat
    pool or round that this record contradicts. A record without the attribute is
    not contradicted (a NIRF rank has no year, an old-shape record no category); a
    record whose round is None, a year with no round breakdown, does contradict a
    stated round.
    """
    year, branch, category, pool = record.get("year"), record.get("branch"), record.get("category"), record.get("pool")
    duration = _program_duration(record.get("program"))
    if context["years"] and year and str(year) not in context["years"]:
        return False
    if context["branches"] and branch and branch not in context["branches"]:
        return False
    if context["durations"] and duration and duration not in context["durations"]:
        return False
    if context["categories"] and category and category not in context["categories"]:
        return False
    if context["pools"] and pool and pool.lower().split("-")[0] not in context["pools"]:
        return False
    if context["rounds"] and "round" in record and str(record["round"]) not in context["rounds"]:
        return False
    return True


def _ungrounded_spans(answer_text, bundle):
    """(start, end, value) for each number in answer_text that the bundle does
    not support: not a value anywhere in the bundle (exact match only,
    deliberately no fuzzy/"close enough" tolerance, since a fabricated figure
    must never slip through), or a value of a record that is not the one the
    answer attaches it to. A round number ("round 3") must be a round of a
    record for the college it sits beside.
    """
    records = bundle["records"]
    grounded = _grounded_value_strings(bundle)
    inputs = _input_value_strings(bundle)
    record_years = {str(r["year"]) for r in records if r.get("year")}
    names = _college_names(bundle)
    forms = [(r, _value_forms(r["value"])) for r in records]
    durations = {d for r in records if (d := _program_duration(r.get("program")))}
    length_starts = {s for s, _ in _program_lengths(answer_text)}
    branches = {r["branch"] for r in records if r.get("branch")}
    segments = _segments(answer_text, _protected_spans(answer_text, branches, names))
    designators = {m.start(1) for m in ROUND_PATTERN.finditer(answer_text)}
    numbers = extract_numbers(answer_text)
    # A year or a round names the figure beside it; only another figure ends
    # the stretch in which a cue word is read.
    figures = [(s, e) for n, s, e in numbers if s not in designators and s not in length_starts and n not in record_years]

    contexts = [_segment_context(answer_text[lo:hi], names, record_years, branches) for lo, hi in segments]
    flagged = []
    for n, start, end in numbers:
        index = next(i for i, (lo, hi) in enumerate(segments) if lo <= start < hi)
        lo, hi = segments[index]
        context = contexts[index]
        candidates = [(r, f) for r, f in forms if r["college_id"] in context["colleges"]]

        if start in designators:
            supported = any(str(r.get("round")) == n for r, _ in candidates)
        elif n in inputs or n in record_years or (n in durations and start in length_starts):
            supported = True
        elif n not in grounded and n.rstrip("%") not in grounded:
            supported = False
        else:
            kinds = _kinds_for(
                answer_text,
                max([e for s, e in figures if e <= start] + [lo]),
                start,
                end,
                end if any(end <= s < hi for s, e in figures) else hi,
            )
            supported = any(
                (kinds is None or r["field"] in kinds) and (n in f or n.rstrip("%") in f) and _agrees(r, context)
                for r, f in candidates
            )
        if not supported:
            flagged.append((start, end, n))
    return flagged


def validate_grounding(answer_text, bundle):
    """Returns the list of numbers in answer_text that the bundle does not
    support - absent from it, or attached to a college, year, category, round,
    seat pool or kind of figure they do not belong to - in order of appearance.
    """
    return [n for _, _, n in _ungrounded_spans(answer_text, bundle)]


def _strip_ungrounded(answer_text, spans):
    """Replaces exactly the flagged spans, last to first so earlier offsets
    stay valid. A global search for the digits would also hit genuine figures
    that contain them (a flagged 3 inside a grounded 39655).
    """
    stripped = answer_text
    for start, end, _ in sorted(spans, reverse=True):
        stripped = stripped[:start] + "[figure not available in the system's data]" + stripped[end:]
    return stripped


# Escalation. When the retry still states a figure the records do not support,
# the figure is stripped (as before) and the answer carries a `verification`
# note: what could not be verified and, when one exists, the closest figure the
# records hold, with all six fields. The note states a figure only as its own
# record reads, so the rejected claim is never repeated as written.
RANK_KINDS = ("actual_closing_rank", "predicted_closing_rank")
KIND_PHRASES = {"actual_closing_rank": "closing rank", "predicted_closing_rank": "forecast closing rank"}
ESCALATION_NOTHING_CLOSE = (
    "I removed a figure I could not verify, and nothing close to it is on record. "
    "Ask about one college and one branch, with your category, and I will check the data."
)
QUOTA_NAMES = {"AI": "All India", "HS": "Home State", "OS": "Other State"}
ESCALATION_WITH_FIGURE = (
    "I removed a figure I could not verify. The closest figure on record is for {college_name}, {branch} ({program}), "
    "{category}, {pool} seats, {quota_text} quota, {year}, {round_text}: {kind_text} {value}. "
    "To check another college or branch, name it and give your category."
)


def _claim_attributes(answer_text, start, end, bundle):
    """What the answer attaches the figure at answer_text[start:end] to: the
    college, branch, category, year and round its segment names, with the
    question's own college, branch and the student's category filling what the
    segment leaves out. None for a part that stays unknown.
    """
    records = bundle["records"]
    branches = {r["branch"] for r in records if r.get("branch")}
    record_years = {str(r["year"]) for r in records if r.get("year")}
    names = _college_names(bundle)
    lo, hi = next((lo, hi) for lo, hi in _segments(answer_text, _protected_spans(answer_text, branches, names)) if lo <= start < hi)
    context = _segment_context(answer_text[lo:hi], names, record_years, branches)
    focus = bundle.get("focus") or {}

    # One college named, or the bundle has only one: that one. None named (the
    # context then holds them all): the college the question named. Several
    # named: unknown.
    colleges = context["colleges"]
    college = next(iter(colleges)) if len(colleges) == 1 else focus.get("college_id") if colleges == set(names) else None
    branch = next(iter(context["branches"])) if len(context["branches"]) == 1 else (None if context["branches"] else focus.get("branch"))
    category = next(iter(context["categories"])) if len(context["categories"]) == 1 else focus.get("category") or "OPEN"
    return {
        "college_id": college,
        "branch": branch,
        "category": category,
        "female_pool": "female" in context["pools"],
        "duration": next(iter(context["durations"])) if len(context["durations"]) == 1 else None,
        "year": int(next(iter(context["years"]))) if len(context["years"]) == 1 else None,
        "round": int(next(iter(context["rounds"]))) if len(context["rounds"]) == 1 else None,
        "kinds": _kinds_for(answer_text, lo, start, end, hi),
    }


def _closest_figure(claim, bundle):
    """The one admission figure in the bundle nearest to a rejected claim, or
    None. Deterministic: the record must be for the claim's exact college and
    branch (without both there is nothing to be close to), then the order is
    category, seat pool, the program the claim names, nearest year (the latest
    year when none is stated), nearest round, then the shorter program (the
    ordinary BTech). Only closing-rank records qualify, and only with
    program, category, pool, quota and year on them, so no figure is ever
    offered without its attribution.
    """
    if claim["college_id"] is None or claim["branch"] is None or (claim["kinds"] and not set(claim["kinds"]) & set(RANK_KINDS)):
        return None
    candidates = [
        r
        for r in bundle["records"]
        if r["field"] in RANK_KINDS
        and r["college_id"] == claim["college_id"]
        and r.get("branch") == claim["branch"]
        and all(r.get(key) for key in ("program", "category", "pool", "quota", "year"))
    ]
    if not candidates:
        return None
    latest = max(r["year"] for r in candidates)

    def order(r):
        year_gap = abs(r["year"] - claim["year"]) if claim["year"] else latest - r["year"]
        round_gap = abs(r["round"] - claim["round"]) if claim["round"] and r["round"] else (1 if claim["round"] else 0)
        # Every record is Gender-Neutral, so a Female-only claim ranks them all alike.
        pool_gap = int(claim["female_pool"] and not r["pool"].lower().startswith("female"))
        duration = _program_duration(r["program"]) or ""
        program_gap = int(bool(claim["duration"]) and duration != claim["duration"])
        return (r["category"] != claim["category"], pool_gap, program_gap, year_gap, round_gap, duration, r.get("program_id", ""), r["value"])

    return min(candidates, key=order)


def _escalation(answer_text, spans, bundle):
    """The `verification` object for an answer whose figures could not all be
    verified: spans are the rejected figures, as (start, end, value).
    """
    start, end, _ = min(spans)
    closest = _closest_figure(_claim_attributes(answer_text, start, end, bundle), bundle)
    if closest is None:
        return {"outcome": "escalate", "unverified_count": len(spans), "closest": None, "message": ESCALATION_NOTHING_CLOSE}
    name = bundle.get("college_names", {}).get(closest["college_id"], closest["college_id"])
    round_ = f"round {closest['round']}" if closest["round"] is not None else "no round data"
    figure = {
        "college_id": closest["college_id"],
        "college_name": name,
        "branch": closest["branch"],
        "program": closest["program"],
        "category": closest["category"],
        "pool": closest["pool"],
        "quota": closest["quota"],
        "year": closest["year"],
        "round": closest["round"],
        "kind": closest["field"],
        "value": closest["value"],
    }
    quota_text = QUOTA_NAMES.get(closest["quota"], closest["quota"])
    message = ESCALATION_WITH_FIGURE.format(**figure, round_text=round_, kind_text=KIND_PHRASES[closest["field"]], quota_text=quota_text)
    return {"outcome": "escalate", "unverified_count": len(spans), "closest": figure, "message": message}


def generate_answer(question, bundle, *, validate=True, escalate=True):
    """Calls the configured LLM, then enforces numeric grounding in code
    before returning - see the module docstring. Never raises for a
    reachability problem; returns a clean error answer instead of ever
    fabricating one (a 413 or 429 from the provider gets its own message,
    PROVIDER_REJECTED_ANSWER). Returns a dict: answer, source_college_ids,
    blocked_ungrounded_figure, error, and `verification` (see _escalation)
    when a figure was stripped but the answer could still be given.

    `validate` and `escalate` exist only for models/eval_counsellor.py, which
    compares the three behaviours: validate=False returns the first answer as
    it came (arm A), escalate=False strips without a note (arm B). The API
    never passes either (tests/test_eval_counsellor.py pins it).
    """
    if bundle["mode"] == "out_of_scope_placement":
        return {"answer": PLACEMENT_DECLINE_ANSWER, "source_college_ids": [], "blocked_ungrounded_figure": False, "error": None}

    context_text = _format_context(bundle)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Context records:\n{context_text}\n\nStudent question: {question}"},
    ]

    model = os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODEL
    try:
        client = _client()
        response = client.chat.completions.create(model=model, messages=messages, temperature=0.2)
        answer_text = _completion_text(response)
    except Exception as exc:
        # 413 (request too large) and 429 (rate limited) mean the provider is
        # up and refused this request; anything else is treated as unreachable.
        rejected = _provider_refused(exc)
        print(f"[counsellor] provider call failed: {type(exc).__name__}, status {getattr(exc, 'status_code', None)}")
        return {
            "answer": PROVIDER_REJECTED_ANSWER if rejected else LLM_UNREACHABLE_ANSWER,
            "source_college_ids": bundle["college_ids"],
            "blocked_ungrounded_figure": False,
            "error": str(exc),
        }

    first_text = answer_text
    ungrounded_spans = _ungrounded_spans(first_text, bundle) if validate else []
    ungrounded = [n for _, _, n in ungrounded_spans]
    blocked = False
    verification = None
    if ungrounded:
        print(f"[counsellor] ungrounded figure(s) caught in first answer: {ungrounded}")
        retry_messages = messages + [
            {"role": "assistant", "content": answer_text},
            {
                "role": "user",
                "content": (
                    "Your answer contained a number that is not in the context records, or that the records give for "
                    f"a different college, year, category, round or kind of figure: {', '.join(ungrounded)}. "
                    "Rewrite your answer using ONLY numbers that appear in the context records above, each with the college, year and category it belongs to. "
                    "If you cannot answer without that number, say plainly that the figure is not available."
                ),
            },
        ]
        try:
            retry_response = client.chat.completions.create(model=model, messages=retry_messages, temperature=0.0)
            retry_text = _completion_text(retry_response)
            retry_spans = _ungrounded_spans(retry_text, bundle)
            if not retry_spans:
                answer_text = retry_text
            else:
                print(f"[counsellor] ungrounded figure(s) still present after retry: {[n for _, _, n in retry_spans]}, stripping")
                answer_text = _strip_ungrounded(retry_text, retry_spans)
                verification = _safe_escalation(retry_text, retry_spans, bundle) if escalate else None
                blocked = True
        except Exception as exc:
            print(f"[counsellor] retry call failed: {type(exc).__name__}, status {getattr(exc, 'status_code', None)}")
            if _provider_refused(exc):
                # The provider turned the retry down: the first answer holds a
                # figure the validator rejected, and there is no second call to fix it.
                return {
                    "answer": PROVIDER_REJECTED_ANSWER,
                    "source_college_ids": bundle["college_ids"],
                    "blocked_ungrounded_figure": True,
                    "error": str(exc),
                }
            answer_text = _strip_ungrounded(first_text, ungrounded_spans)
            verification = _safe_escalation(first_text, ungrounded_spans, bundle) if escalate else None
            blocked = True

    result = {"answer": answer_text, "source_college_ids": bundle["college_ids"], "blocked_ungrounded_figure": blocked, "error": None}
    if verification is not None:
        result["verification"] = verification
    return result


def _provider_refused(exc):
    return isinstance(exc, APIStatusError) and exc.status_code in (413, 429)


def _safe_escalation(answer_text, spans, bundle):
    """The verification note is additive (Rules.md section 8): if building it
    fails, the answer still goes out, stripped, without one.
    """
    try:
        return _escalation(answer_text, spans, bundle)
    except Exception as exc:
        print(f"[counsellor] verification note failed, answering without it: {type(exc).__name__}")
        return None
