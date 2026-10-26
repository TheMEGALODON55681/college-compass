"""A question that names a college and comes with a student profile used to get
that college's forecast rows only, and eligibility lists only the branches a
student can reach. A rank outside the college's reach left the model with a NIRF
rank and a fee and nothing else, and it answered that the records held no
closing rank. A branch the question does not name precisely ("CSE") hid behind
the reachable branches the same way. A named college now always carries its real
history, the Gender-Neutral latest-year rows a question without a profile gets,
and the profile adds the forecast rows. Each expected set comes from its own SQL
against the real database.
"""

import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api.main as main_module
from counsellor_fakes import FakeClient, FixedEncoder
from db.connection import get_database_url, get_engine
from models.counsellor import generate_answer
from models.counsellor_retrieval import build_context_bundle
from test_memory_fit_regression import _client

IIT_DELHI = "indian-institute-of-technology-delhi"
MAX_PROMPT_TOKENS = 7000
# The ratio test_counsellor_context_size.py uses, rounded down so the estimate errs high.
CHARS_PER_TOKEN = 3.4
QUESTION = "What is the closing rank for Computer Science at IIT Delhi?"
# Rank 12480 reaches no IIT Delhi branch; rank 1000 reaches the less competitive
# ones but not Computer Science; rank 150 reaches Computer Science.
OUT_OF_REACH = {"jee_rank": 12480, "category": "OPEN", "home_state": "Delhi"}
PARTLY_IN_REACH = {"jee_rank": 1000, "category": "OPEN", "home_state": "Delhi"}
IN_REACH = {"jee_rank": 150, "category": "OPEN", "home_state": "Delhi"}


def _state():
    _client()
    return main_module.model_state


def _gender_neutral_cse_ranks():
    sql = text(
        """
        SELECT cu.closing_rank FROM cutoffs cu JOIN programs p ON cu.program_id = p.program_id
        WHERE cu.college_id = :c AND cu.quota = 'AI' AND cu.gender_seat_type = 'Gender-Neutral'
          AND p.branch_name LIKE '%Computer Science and Engineering%'
          AND cu.year = (SELECT MAX(year) FROM cutoffs WHERE college_id = :c AND quota = 'AI' AND gender_seat_type = 'Gender-Neutral')
          AND cu.round IS NULL
        """
    )
    with get_engine(get_database_url()).connect() as conn:
        return Counter(r[0] for r in conn.execute(sql, {"c": IIT_DELHI}))


def _actual_ranks(bundle):
    return Counter(r["value"] for r in bundle["records"] if r["field"] == "actual_closing_rank")


def _fields(bundle):
    return Counter(r["field"] for r in bundle["records"])


def test_student_out_of_reach_still_gets_the_named_colleges_closing_ranks():
    expected = _gender_neutral_cse_ranks()
    assert expected, "no Computer Science rows for IIT Delhi: the test would prove nothing"

    bundle = build_context_bundle(QUESTION, OUT_OF_REACH, _state())

    assert bundle["mode"] == "structured"
    assert _actual_ranks(bundle) == expected


def test_student_out_of_reach_gets_the_same_rows_as_a_question_without_a_profile():
    without = build_context_bundle(QUESTION, None, _state())
    with_profile = build_context_bundle(QUESTION, OUT_OF_REACH, _state())

    def rows(bundle):  # a capped history is sorted, an uncapped one is not: compare as sets of rows
        return Counter((r["field"], r["label"], r["value"]) for r in bundle["records"])

    assert rows(with_profile) == rows(without)


def test_branch_the_question_does_not_name_precisely_keeps_its_history_beside_reachable_branches():
    """The question says "CSE", which is not read as a branch, so the profile
    adds the forecast rows of the branches the student can reach (not Computer
    Science). The history of the college must still hold the Computer Science
    rows.
    """
    expected = _gender_neutral_cse_ranks()

    bundle = build_context_bundle("What is the closing rank for CSE at IIT Delhi?", PARTLY_IN_REACH, _state())

    assert _fields(bundle)["predicted_closing_rank"] >= 1, "nothing reachable: the test would prove nothing"
    assert not expected - _actual_ranks(bundle)


def test_student_in_reach_gets_the_forecast_and_the_actual_ranks():
    bundle = build_context_bundle(QUESTION, IN_REACH, _state())

    fields = _fields(bundle)
    assert fields["predicted_closing_rank"] >= 1 and fields["admission_probability"] >= 1
    assert _actual_ranks(bundle) == _gender_neutral_cse_ranks()


def test_similar_question_from_a_student_out_of_reach_stays_under_the_provider_limit(monkeypatch):
    """The named college's history shares the prompt with the forecast rows of
    the neighbours the student can reach. Real neighbours, so a state copy with
    the real encoder (the shared one stays unloaded). The pairs are the worst
    prompts of the sweep over 133 colleges, 16 profiles and two phrasings.
    """
    from models.onnx_encoder import OnnxSentenceEncoder

    state = {**_state(), "embedding_model": OnnxSentenceEncoder()}
    worst_cases = [
        ("colleges similar to IIT Delhi", {"jee_rank": 8000, "category": "OPEN", "home_state": "Kerala"}),
        ("colleges similar to IIT Patna", {"jee_rank": 8000, "category": "OBC-NCL", "home_state": "Delhi"}),
    ]
    for question, profile in worst_cases:
        client = FakeClient(["ok"])
        monkeypatch.setattr("models.counsellor._client", lambda: client)
        bundle = build_context_bundle(question, profile, state)
        generate_answer(question, bundle)

        prompt = "".join(m["content"] for m in client.calls[0])
        assert bundle["mode"] == "mixed"
        assert len(prompt) / CHARS_PER_TOKEN < MAX_PROMPT_TOKENS, question


def _state_with_stub_encoder():
    # A copy with a stub encoder: the shared app state must not gain the real
    # one, test_lazy_encoder asserts it is absent until a semantic question.
    return {**_state(), "embedding_model": FixedEncoder(_state()["similarity_bundle"][0].d)}


def test_neighbours_of_a_similar_question_get_no_history():
    """Only the college the student named carries its history; the alternatives
    listed beside it stay limited to what the student can reach.
    """
    bundle = build_context_bundle("colleges similar to IIT Delhi", OUT_OF_REACH, _state_with_stub_encoder())

    assert bundle["mode"] == "mixed"
    history_owners = {r["college_id"] for r in bundle["records"] if r["field"] == "actual_closing_rank"}
    assert history_owners == {IIT_DELHI}


def test_similar_question_from_a_student_who_can_reach_the_college_gets_the_forecast_only():
    """Next to five alternatives the prompt has no room for the history as well:
    a student who can reach the named college gets its forecast rows, as before.
    """
    bundle = build_context_bundle("colleges similar to IIT Delhi", IN_REACH, _state_with_stub_encoder())

    assert bundle["mode"] == "mixed"
    assert _fields(bundle)["predicted_closing_rank"] >= 1
    assert not _actual_ranks(bundle)


def test_one_college_question_from_a_student_stays_under_the_provider_limit(monkeypatch):
    """The history of a named college sits beside its forecast rows. Uncapped,
    IIT Patna (149 rows) came to 7,880 tokens for this profile, and 32 of 3,536
    college, profile and phrasing combinations passed 7,000.
    """
    question = "closing ranks for IIT Patna"
    client = FakeClient(["ok"])
    monkeypatch.setattr("models.counsellor._client", lambda: client)
    bundle = build_context_bundle(question, {"jee_rank": 1500, "category": "EWS"}, _state())
    generate_answer(question, bundle)

    prompt = "".join(m["content"] for m in client.calls[0])
    assert bundle["mode"] == "structured"
    assert len(prompt) / CHARS_PER_TOKEN < MAX_PROMPT_TOKENS
