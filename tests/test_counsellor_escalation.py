"""The escalate outcome. When the retry still states a figure the records do not
support, the figure is stripped and the answer carries a `verification` note:
what could not be verified and the closest figure on record, with all six
fields, or a plain statement that nothing close is on record. Never reachable
from the placement decline or the unreachable path, never a figure without its
attribution, and the rejected claim is never repeated as written (a record that
holds the same value is stated with its own attributes).
"""

import json
import random
import re
import sys
from pathlib import Path

import httpx
import openai
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from counsellor_fakes import FakeClient
from models import counsellor
from models.counsellor import (
    ESCALATION_NOTHING_CLOSE,
    LLM_UNREACHABLE_ANSWER,
    PLACEMENT_DECLINE_ANSWER,
    PROVIDER_REJECTED_ANSWER,
    _closest_figure,
    generate_answer,
)
from models.counsellor_retrieval import build_context_bundle
from test_counsellor_out_of_reach import _state

NEAR_MISS = [
    q for q in json.loads((Path(__file__).parent / "fixtures" / "eval" / "counsellor_questions.json").read_text(encoding="utf-8"))["questions"] if q["class"] == "near_miss"
]

DELHI = "indian-institute-of-technology-delhi"
BOMBAY = "indian-institute-of-technology-bombay"
CSE = "Computer Science and Engineering"
REQUEST = httpx.Request("POST", "http://llm.test/v1/chat/completions")
QUESTION = "What is the closing rank for Computer Science at IIT Delhi?"


def _rank(college_id, branch, value, *, year=2024, category="OPEN", round_=None, program="four-year BTech", program_id="p4", field="actual_closing_rank", quota="AI"):
    return {
        "college_id": college_id,
        "year": year,
        "field": field,
        "value": value,
        "label": f"{branch} ({program}) closing rank, {category}",
        "program_id": program_id,
        "program": program,
        "branch": branch,
        "category": category,
        "quota": quota,
        "pool": "Gender-Neutral",
        "round": round_,
    }


def _bundle(*records, focus=None):
    return {
        "mode": "structured",
        "records": list(records),
        "college_ids": sorted({r["college_id"] for r in records}),
        "college_aliases": {DELHI: ["iit delhi", "indian institute of technology delhi"], BOMBAY: ["iit bombay"]},
        "college_names": {DELHI: "Indian Institute of Technology Delhi", BOMBAY: "Indian Institute of Technology Bombay"},
        "focus": focus or {"college_id": DELHI, "branch": CSE, "category": None},
        "student_inputs": {},
    }


BUNDLE = _bundle(
    _rank(DELHI, CSE, 116),
    _rank(DELHI, CSE, 204, program="five-year dual degree", program_id="p5"),
    _rank(DELHI, CSE, 445, category="SC"),
    _rank(DELHI, "Mathematics and Computing", 330),
)
FABRICATED = "In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi was 99999."


def _refusal(status):
    cls = openai.RateLimitError if status == 429 else openai.APIStatusError
    return cls("refused", response=httpx.Response(status, request=REQUEST), body=None)


def _run(monkeypatch, replies, bundle=BUNDLE):
    client = FakeClient(replies)
    monkeypatch.setattr("models.counsellor._client", lambda: client)
    return generate_answer(QUESTION, bundle), client


# --- where escalation must not be reachable -------------------------------------------------


def test_placement_decline_never_escalates(monkeypatch):
    bundle = {"mode": "out_of_scope_placement", "records": [], "college_ids": [], "student_inputs": {}}
    result, client = _run(monkeypatch, [], bundle)

    assert result["answer"] == PLACEMENT_DECLINE_ANSWER
    assert "verification" not in result
    assert client.calls == []


@pytest.mark.parametrize("error", [openai.APIConnectionError(request=REQUEST), _refusal(413), _refusal(429)], ids=["unreachable", "413", "429"])
def test_failed_first_call_never_escalates(monkeypatch, error):
    result, _ = _run(monkeypatch, [error])

    assert result["answer"] in (LLM_UNREACHABLE_ANSWER, PROVIDER_REJECTED_ANSWER)
    assert "verification" not in result


@pytest.mark.parametrize("reply", [None, "", "   "], ids=["none", "empty", "blank"])
def test_empty_first_completion_reads_as_unreachable(monkeypatch, reply):
    result, _ = _run(monkeypatch, [reply])

    assert result["answer"] == LLM_UNREACHABLE_ANSWER
    assert "verification" not in result


def test_clean_answer_has_no_note(monkeypatch):
    result, _ = _run(monkeypatch, ["In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi was 116."])

    assert "verification" not in result and result["blocked_ungrounded_figure"] is False


def test_corrected_retry_has_no_note(monkeypatch):
    result, client = _run(monkeypatch, [FABRICATED, "In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi was 116."])

    assert len(client.calls) == 2
    assert "verification" not in result and result["blocked_ungrounded_figure"] is False


# --- what the note says -----------------------------------------------------------------------


def test_failed_retry_strips_the_figure_and_offers_the_closest_one_with_six_fields(monkeypatch):
    result, _ = _run(monkeypatch, [FABRICATED, FABRICATED])

    note = result["verification"]
    closest = note["closest"]
    assert result["blocked_ungrounded_figure"] is True
    assert "99999" not in result["answer"] and "99999" not in note["message"]
    assert note["outcome"] == "escalate" and note["unverified_count"] == 1
    # The claim names 2024 and OPEN for the branch: the two programs tie, the shorter (four-year) one wins.
    assert (closest["college_id"], closest["branch"], closest["category"], closest["pool"], closest["year"], closest["round"]) == (
        DELHI, CSE, "OPEN", "Gender-Neutral", 2024, None
    )
    assert closest["program"] == "four-year BTech"
    for text in ("Indian Institute of Technology Delhi", CSE, closest["program"], "OPEN", "Gender-Neutral", "2024", "no round data", str(closest["value"])):
        assert text in note["message"]


def test_a_question_that_says_computer_science_still_finds_the_closest_figure(monkeypatch):
    """Real bundle, answer that does not spell the branch out: the question's own
    branch fills the gap. The matcher "Computer Science" is not a record's branch
    name, so the bundle has to resolve it to one.
    """
    bundle = build_context_bundle(QUESTION, None, _state())
    guess = "The closing rank for Computer Science at IIT Delhi is 99999."
    result, _ = _run(monkeypatch, [guess, guess], bundle)

    note = result["verification"]
    assert note["closest"] is not None
    assert (note["closest"]["college_id"], note["closest"]["branch"]) == (DELHI, CSE)
    assert "99999" not in result["answer"] and "99999" not in note["message"]


@pytest.mark.parametrize("item", NEAR_MISS, ids=[q["id"] for q in NEAR_MISS])
def test_the_focus_branch_of_every_near_miss_question_is_a_record_branch(item):
    bundle = build_context_bundle(item["question"], item["student_profile"], _state())
    branches = {r["branch"] for r in bundle["records"] if r.get("branch")}

    assert bundle["focus"]["branch"] in branches | {None}


def test_a_neighbours_branch_never_becomes_the_focus(monkeypatch):
    """The question names IIT Delhi. A similar college whose own branch is called
    just "Computer Science" (IIIT Lucknow is) must not displace Delhi's.
    """
    neighbour = {"college_id": "some-other-institute", "year": 2024, "field": "actual_closing_rank", "value": 1, "label": "x", "branch": "Computer Science"}
    monkeypatch.setattr("models.counsellor_retrieval._semantic_records", lambda *args, **kwargs: [neighbour])
    bundle = build_context_bundle("Computer Science at IIT Delhi, and colleges similar to it", None, _state())

    assert bundle["mode"] == "mixed"
    assert bundle["focus"]["branch"] == CSE


def test_the_category_a_question_names_is_the_focus_category(monkeypatch):
    sc_question = "What is the SC closing rank for Computer Science at IIT Delhi?"
    state = _state()
    assert build_context_bundle(sc_question, None, state)["focus"]["category"] == "SC"
    assert build_context_bundle(sc_question, {"jee_rank": 5000, "category": "OPEN", "home_state": "Delhi"}, state)["focus"]["category"] == "SC"
    assert build_context_bundle(QUESTION, {"jee_rank": 5000, "category": "OBC-NCL", "home_state": "Delhi"}, state)["focus"]["category"] == "OBC-NCL"
    assert build_context_bundle(QUESTION, None, state)["focus"]["category"] is None
    open_question = "What is the OPEN closing rank for Computer Science at IIT Delhi?"
    assert build_context_bundle(open_question, {"jee_rank": 5000, "category": "SC", "home_state": "Delhi"}, state)["focus"]["category"] == "OPEN"
    two_named = "What are the SC and ST closing ranks for Computer Science at IIT Delhi?"
    assert build_context_bundle(two_named, {"jee_rank": 5000, "category": "OBC-NCL", "home_state": "Delhi"}, state)["focus"]["category"] == "OBC-NCL"

    bundle = build_context_bundle(sc_question, None, state)
    guess = "The closing rank for Computer Science at IIT Delhi is 99999."
    result, _ = _run(monkeypatch, [guess, guess], bundle)
    assert result["verification"]["closest"]["category"] == "SC"


def test_quota_is_named_in_the_note_and_kept_on_the_figure(monkeypatch):
    other_state = _bundle(_rank(DELHI, CSE, 116, quota="OS"))
    result, _ = _run(monkeypatch, [FABRICATED, FABRICATED], other_state)

    note = result["verification"]
    assert note["closest"]["quota"] == "OS"
    assert "Other State quota" in note["message"]


def test_retry_that_cannot_run_still_strips_and_escalates(monkeypatch):
    result, _ = _run(monkeypatch, [FABRICATED, openai.APIConnectionError(request=REQUEST)])

    assert "99999" not in result["answer"]
    assert result["blocked_ungrounded_figure"] is True
    assert result["verification"]["closest"]["value"] == 116


def test_nothing_close_says_so_in_one_sentence_pair_without_a_figure(monkeypatch):
    other = _bundle(_rank(BOMBAY, "Mechanical Engineering", 1782), focus={"college_id": None, "branch": None, "category": None})
    answer = "In 2025, the OPEN closing rank for Quantum Engineering at IIT Delhi was 99999."
    result, _ = _run(monkeypatch, [answer, answer], other)

    note = result["verification"]
    assert note["closest"] is None
    assert note["message"] == ESCALATION_NOTHING_CLOSE
    assert not re.search(r"\d", note["message"])


def test_failure_to_build_the_note_still_returns_the_stripped_answer(monkeypatch):
    def boom(*args):
        raise RuntimeError("note failed")

    monkeypatch.setattr(counsellor, "_escalation", boom)
    result, _ = _run(monkeypatch, [FABRICATED, FABRICATED])

    assert "99999" not in result["answer"] and result["blocked_ungrounded_figure"] is True
    assert "verification" not in result


# --- selection order -----------------------------------------------------------------------


def _claim(**overrides):
    return {"college_id": DELHI, "branch": CSE, "category": "OPEN", "female_pool": False, "duration": None, "year": None, "round": None, "kinds": None, **overrides}


def test_selection_needs_the_exact_college_and_branch():
    assert _closest_figure(_claim(branch="Civil Engineering"), BUNDLE) is None
    assert _closest_figure(_claim(branch=None), BUNDLE) is None
    assert _closest_figure(_claim(college_id=None), BUNDLE) is None
    assert _closest_figure(_claim(college_id=BOMBAY), BUNDLE) is None


def test_category_outranks_year():
    bundle = _bundle(_rank(DELHI, CSE, 116, year=2024), _rank(DELHI, CSE, 445, year=2022, category="SC"))

    assert _closest_figure(_claim(category="SC"), bundle)["value"] == 445
    assert _closest_figure(_claim(category="OPEN"), bundle)["value"] == 116


def test_nearest_year_and_the_latest_when_none_is_stated():
    bundle = _bundle(_rank(DELHI, CSE, 100, year=2022), _rank(DELHI, CSE, 116, year=2024), _rank(DELHI, CSE, 120, year=2025, field="predicted_closing_rank"))

    assert _closest_figure(_claim(year=2023), bundle)["value"] == 100
    assert _closest_figure(_claim(year=2025), bundle)["field"] == "predicted_closing_rank"
    assert _closest_figure(_claim(year=None), bundle)["year"] == 2025


def test_nearest_round_within_a_year():
    bundle = _bundle(_rank(DELHI, CSE, 100, year=2021, round_=1), _rank(DELHI, CSE, 90, year=2021, round_=5))

    assert _closest_figure(_claim(year=2021, round=4), bundle)["value"] == 90
    assert _closest_figure(_claim(year=2021, round=2), bundle)["value"] == 100


def test_the_program_the_claim_names_outranks_the_nearer_year():
    bundle = _bundle(_rank(DELHI, CSE, 116, year=2024), _rank(DELHI, CSE, 204, year=2022, program="five-year dual degree", program_id="p5"))

    assert _closest_figure(_claim(duration="5", year=2024), bundle)["value"] == 204
    assert _closest_figure(_claim(duration="4", year=2022), bundle)["value"] == 116


def test_the_program_a_sentence_names_picks_the_figure_in_the_note(monkeypatch):
    """The whole path: a rejected figure under "five-year dual degree" is offered the
    dual degree's rank, not the ordinary BTech's.
    """
    guess = "In 2024, the OPEN closing rank for Computer Science and Engineering (five-year dual degree) at IIT Delhi was 99999."
    result, _ = _run(monkeypatch, [guess, guess])

    assert (result["verification"]["closest"]["program"], result["verification"]["closest"]["value"]) == ("five-year dual degree", 204)


def test_a_claim_with_no_program_gets_the_four_year_one():
    """The ordinary BTech is what a bare "Computer Science" means."""
    records = [_rank(DELHI, CSE, 204, program="five-year dual degree", program_id="p1"), _rank(DELHI, CSE, 116, program_id="p9")]

    assert _closest_figure(_claim(), _bundle(*records))["value"] == 116


def test_ties_resolve_the_same_way_every_time():
    records = list(BUNDLE["records"])
    picks = set()
    for seed in range(8):
        random.Random(seed).shuffle(records)
        picks.add(_closest_figure(_claim(), _bundle(*records))["program_id"])
    assert picks == {"p4"}


def test_only_complete_closing_rank_records_qualify():
    college_level = {"college_id": DELHI, "year": None, "field": "nirf_rank", "value": 2, "label": "latest NIRF rank"}
    no_program = {k: v for k, v in _rank(DELHI, CSE, 116).items() if k != "program"}
    no_pool = {**_rank(DELHI, CSE, 117), "pool": None}
    no_quota = {**_rank(DELHI, CSE, 118), "quota": None}
    probability = _rank(DELHI, CSE, 0.9, field="admission_probability")

    assert _closest_figure(_claim(), _bundle(college_level, no_program, no_pool, no_quota, probability)) is None


def test_a_claim_about_a_fee_or_a_nirf_rank_gets_no_closing_rank():
    assert _closest_figure(_claim(kinds={"fees_annual_lakhs"}), BUNDLE) is None
    assert _closest_figure(_claim(kinds={"nirf_rank"}), BUNDLE) is None
    assert _closest_figure(_claim(kinds={"actual_closing_rank"}), BUNDLE) is not None


def test_no_note_ever_names_a_figure_without_its_attribution():
    """Every rank record of a real-shaped bundle, offered alone."""
    for record in BUNDLE["records"]:
        note = counsellor._escalation(FABRICATED, [(len(FABRICATED) - 6, len(FABRICATED) - 1, "99999")], _bundle(record))
        closest = note["closest"]
        if closest is None:
            assert note["message"] == ESCALATION_NOTHING_CLOSE
            continue
        for key in ("college_id", "college_name", "branch", "program", "category", "pool", "quota", "year", "kind", "value"):
            assert closest[key] not in (None, ""), key
        assert "round" in closest
