"""Stripping an ungrounded figure must touch only the flagged span of the
answer. The real case is tests/fixtures/baseline/chat_semantic_fuzzy.json: the
model numbered its steps "1. 2. 3.", the validator flagged those markers, and
a global substring replace turned the genuine forecast year 2025 and the
genuine closing rank 39655 into "[figure not available ...]0[figure ...]5" and
"[figure ...]9655".
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from counsellor_fakes import FakeClient
from models.counsellor import extract_numbers, generate_answer, validate_grounding

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "baseline" / "chat_semantic_fuzzy.json"
PLACEHOLDER = "[figure not available in the system's data]"  # the user-visible text, pinned here on purpose

# The model's steps from the fixture, with the markers and numbers intact.
LIST_ANSWER = (
    "The Computer Science programmes in the 2025 forecast have predicted closing ranks of 39655, 39676 and 30755.\n"
    "\n"
    "How to use this information:\n"
    "1. Check your own JEE Main rank and your category.\n"
    "2. Compare your rank with the closing ranks above.\n"
    "3. Decide which specialisation fits your interests.\n"
)


def _fixture_bundle():
    """A bundle whose grounded values are exactly the ones the fixture recorded
    for that question, so 2025 and the closing ranks are genuine and 1, 2, 3
    are not.
    """
    grounded = json.loads(FIXTURE.read_text(encoding="utf-8"))["grounded_values"]
    records = [
        {"college_id": "indian-institute-of-information-technology-agartala", "year": None, "field": "closing_rank", "value": int(v), "label": "closing rank"}
        for v in grounded
        if v.isdigit()
    ]
    return {"mode": "semantic", "records": records, "college_ids": ["indian-institute-of-information-technology-agartala"], "student_inputs": {"jee_rank": 8000}}


def test_extract_numbers_returns_each_number_with_its_span():
    text = "rank 1,234, then 5"

    found = extract_numbers(text)

    assert [(n, text[start:end]) for n, start, end in found] == [("1234", "1,234"), ("5", "5")]


def test_numbered_list_markers_are_not_figures():
    """A list ordinal is formatting, not a claim, so it is never checked
    against the bundle. A real figure inside a list item still is.
    """
    bundle = _fixture_bundle()

    assert validate_grounding(LIST_ANSWER, bundle) == []
    assert validate_grounding("**1.** Check your rank.\n**2. Compare** with 39655.\n3) Decide.", bundle) == []
    assert validate_grounding("1. The closing rank is 12345.", bundle) == ["12345"]


def test_numbered_list_answer_is_returned_untouched(monkeypatch):
    """No retry and no strip: one scripted response, and the answer comes back
    byte for byte.
    """
    client = FakeClient([LIST_ANSWER])
    monkeypatch.setattr("models.counsellor._client", lambda: client)

    result = generate_answer("What are some good CS options near my rank?", _fixture_bundle())

    assert result["answer"] == LIST_ANSWER
    assert result["blocked_ungrounded_figure"] is False
    assert len(client.calls) == 1


def test_strip_replaces_only_the_flagged_span(monkeypatch):
    """The fabricated 3 is a substring of the genuine 39655 and 30755. Only
    the flagged occurrence goes.
    """
    answer = "In 2025 the closing rank is 39655, and 3 of these options look safe."
    monkeypatch.setattr("models.counsellor._client", lambda: FakeClient([answer, answer]))

    result = generate_answer("What are some good CS options near my rank?", _fixture_bundle())

    assert result["blocked_ungrounded_figure"] is True
    assert result["answer"] == f"In 2025 the closing rank is 39655, and {PLACEHOLDER} of these options look safe."


def test_strip_removes_a_figure_written_with_thousands_separators(monkeypatch):
    answer = "The predicted closing rank is 12,345 for 2025."
    monkeypatch.setattr("models.counsellor._client", lambda: FakeClient([answer, answer]))

    result = generate_answer("What is the closing rank?", _fixture_bundle())

    assert result["blocked_ungrounded_figure"] is True
    assert result["answer"] == f"The predicted closing rank is {PLACEHOLDER} for 2025."
