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


def _grounded_value_strings(bundle):
    """Every numeric value the bundle actually contains, normalized the same
    way as extract_numbers, plus each record's own year (a legitimate,
    sourced number - "the 2025 forecast" - not a fabricated figure) and the
    student's own stated inputs (their own rank/budget, echoed back, is not
    a fabricated system number either).
    """
    grounded = set()
    for r in bundle["records"]:
        value = r["value"]
        if isinstance(value, bool):
            pass
        elif isinstance(value, int):
            grounded.add(str(value))
        elif isinstance(value, float):
            grounded.add(str(value))
            trimmed = f"{value:.4f}".rstrip("0").rstrip(".")
            grounded.add(trimmed)
            if 0 <= value <= 1:
                pct = round(value * 100)
                grounded.add(str(pct))
                grounded.add(f"{pct}%")
        if r.get("year"):
            grounded.add(str(r["year"]))

    for value in bundle.get("student_inputs", {}).values():
        grounded.add(str(value))
        if isinstance(value, float):
            grounded.add(f"{value:.4f}".rstrip("0").rstrip("."))

    return grounded


def _ungrounded_spans(answer_text, bundle):
    """(start, end, value) for each number in answer_text that does not appear
    anywhere in the bundle's grounded values - exact match only, deliberately
    no fuzzy/"close enough" tolerance, since the whole point is that a
    fabricated figure must never slip through.
    """
    grounded = _grounded_value_strings(bundle)
    return [
        (start, end, n)
        for n, start, end in extract_numbers(answer_text)
        if n not in grounded and n.rstrip("%") not in grounded
    ]


def validate_grounding(answer_text, bundle):
    """Returns the list of numbers in answer_text that do not appear anywhere
    in the bundle's grounded values, in order of appearance.
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


def generate_answer(question, bundle):
    """Calls the configured LLM, then enforces numeric grounding in code
    before returning - see the module docstring. Never raises for a
    reachability problem; returns a clean error answer instead of ever
    fabricating one (a 413 or 429 from the provider gets its own message,
    PROVIDER_REJECTED_ANSWER). Returns a dict: answer, source_college_ids,
    blocked_ungrounded_figure, error.
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
        answer_text = response.choices[0].message.content
    except Exception as exc:
        # 413 (request too large) and 429 (rate limited) mean the provider is
        # up and refused this request; anything else is treated as unreachable.
        rejected = isinstance(exc, APIStatusError) and exc.status_code in (413, 429)
        return {
            "answer": PROVIDER_REJECTED_ANSWER if rejected else LLM_UNREACHABLE_ANSWER,
            "source_college_ids": bundle["college_ids"],
            "blocked_ungrounded_figure": False,
            "error": str(exc),
        }

    ungrounded_spans = _ungrounded_spans(answer_text, bundle)
    ungrounded = [n for _, _, n in ungrounded_spans]
    blocked = False
    if ungrounded:
        print(f"[counsellor] ungrounded figure(s) caught in first answer: {ungrounded}")
        retry_messages = messages + [
            {"role": "assistant", "content": answer_text},
            {
                "role": "user",
                "content": (
                    f"Your answer contained a number not present in the context records: {', '.join(ungrounded)}. "
                    "Rewrite your answer using ONLY numbers that appear in the context records above. "
                    "If you cannot answer without that number, say plainly that the figure is not available."
                ),
            },
        ]
        try:
            retry_response = client.chat.completions.create(model=model, messages=retry_messages, temperature=0.0)
            retry_text = retry_response.choices[0].message.content
            retry_spans = _ungrounded_spans(retry_text, bundle)
            if not retry_spans:
                answer_text = retry_text
            else:
                print(f"[counsellor] ungrounded figure(s) still present after retry: {[n for _, _, n in retry_spans]}, stripping")
                answer_text = _strip_ungrounded(retry_text, retry_spans)
                blocked = True
        except Exception:
            answer_text = _strip_ungrounded(answer_text, ungrounded_spans)
            blocked = True

    return {"answer": answer_text, "source_college_ids": bundle["college_ids"], "blocked_ungrounded_figure": blocked, "error": None}
