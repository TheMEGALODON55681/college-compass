"""The honesty backbone's required test: a fabricated rank in a generated
answer must be caught and blocked, never shown to the student. Covers the
validator directly (the core requirement) and the full generate_answer path
(mocked LLM client, plus one real test against an intentionally unreachable
endpoint to prove no answer is ever fabricated when the LLM can't be reached).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.counsellor import LLM_UNREACHABLE_ANSWER, PLACEMENT_DECLINE_ANSWER, generate_answer, validate_grounding


def _sample_bundle():
    return {
        "mode": "structured",
        "records": [
            {
                "college_id": "indian-institute-of-technology-bombay",
                "year": 2025,
                "field": "predicted_closing_rank",
                "value": 7445,
                "label": "Computer Science and Engineering predicted closing rank (2025 forecast, quota AI, category OPEN)",
            },
            {
                "college_id": "indian-institute-of-technology-bombay",
                "year": 2025,
                "field": "admission_probability",
                "value": 0.85,
                "label": "Computer Science and Engineering calibrated admission probability",
            },
            {
                "college_id": "indian-institute-of-technology-bombay",
                "year": None,
                "field": "nirf_rank",
                "value": 3,
                "label": "latest NIRF rank",
            },
        ],
        "college_ids": ["indian-institute-of-technology-bombay"],
        "student_inputs": {"jee_rank": 5000},
    }


def test_validator_catches_fabricated_rank():
    bundle = _sample_bundle()
    fabricated_answer = "You should comfortably get in - the predicted closing rank is around 9999 for this branch."

    ungrounded = validate_grounding(fabricated_answer, bundle)

    assert "9999" in ungrounded


def test_validator_allows_grounded_numbers():
    bundle = _sample_bundle()
    grounded_answer = (
        "At indian-institute-of-technology-bombay, Computer Science and Engineering has a predicted closing rank "
        "of 7445 for 2025 (quota AI, category OPEN), with a calibrated admission probability of 85%. "
        "It is ranked 3 in the latest NIRF list. Your rank of 5000 is well within range."
    )

    ungrounded = validate_grounding(grounded_answer, bundle)

    assert ungrounded == []


def test_validator_allows_student_own_rank_without_flagging():
    bundle = _sample_bundle()
    answer = "With your rank of 5000, this branch is a safe bet."

    ungrounded = validate_grounding(answer, bundle)

    assert ungrounded == []


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, model, messages, temperature=0.2):
        return self._responses.pop(0)


class _FakeChat:
    def __init__(self, responses):
        self.completions = _FakeCompletions(responses)


class _FakeClient:
    def __init__(self, responses):
        self.chat = _FakeChat(responses)


def test_generate_answer_blocks_fabricated_number_when_retry_still_fabricates(monkeypatch):
    """First LLM response fabricates a rank, the retry response fabricates a
    different one too - generate_answer must never surface either, and must
    report blocked_ungrounded_figure=True.
    """
    bundle = _sample_bundle()
    fake_client = _FakeClient(
        [
            _FakeResponse("The predicted closing rank at indian-institute-of-technology-bombay is 12345."),
            _FakeResponse("The predicted closing rank at indian-institute-of-technology-bombay is 54321."),
        ]
    )
    monkeypatch.setattr("models.counsellor._client", lambda: fake_client)

    result = generate_answer("What is the closing rank for CSE at IIT Bombay?", bundle)

    assert result["blocked_ungrounded_figure"] is True
    assert "12345" not in result["answer"]
    assert "54321" not in result["answer"]
    assert result["error"] is None


def test_generate_answer_accepts_corrected_retry():
    """First response fabricates, the retry response uses only grounded
    numbers - the corrected retry should be returned as-is, not stripped.
    """
    bundle = _sample_bundle()
    fake_client = _FakeClient(
        [
            _FakeResponse("The predicted closing rank is 99999, way off."),
            _FakeResponse("The predicted closing rank at indian-institute-of-technology-bombay is 7445 for 2025."),
        ]
    )

    from models import counsellor

    original_client = counsellor._client
    counsellor._client = lambda: fake_client
    try:
        result = counsellor.generate_answer("What is the closing rank for CSE at IIT Bombay?", bundle)
    finally:
        counsellor._client = original_client

    assert result["blocked_ungrounded_figure"] is False
    assert "7445" in result["answer"]
    assert "99999" not in result["answer"]


def test_generate_answer_never_fabricates_when_llm_unreachable(monkeypatch):
    """No mocking here - LLM_ENDPOINT points at a port nothing is listening
    on, so the real OpenAI client raises a real connection error. The
    definition of done requires a clean error, never a fabricated answer.
    """
    monkeypatch.setenv("LLM_ENDPOINT", "http://localhost:1/v1")
    bundle = _sample_bundle()

    result = generate_answer("What is the closing rank for CSE at IIT Bombay?", bundle)

    assert result["error"] is not None
    assert "9999" not in result["answer"]
    assert "7445" not in result["answer"]
    assert result["answer"] == LLM_UNREACHABLE_ANSWER


def test_placement_question_declined_without_calling_llm():
    bundle = {"mode": "out_of_scope_placement", "records": [], "college_ids": [], "student_inputs": {}}

    result = generate_answer("What is the average placement package at IIT Bombay?", bundle)

    assert result["answer"] == PLACEMENT_DECLINE_ANSWER
    assert result["blocked_ungrounded_figure"] is False
