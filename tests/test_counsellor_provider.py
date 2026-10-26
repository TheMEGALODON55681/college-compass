"""A provider that turns a request down (413 too large, 429 rate limited) gets
its own fixed answer, not the "language model is not reachable" one: the
server is up, the request was refused. Neither answer may carry a number, and
a connection failure must still read as unreachable.
"""

import re
import sys
from pathlib import Path

import httpx
import openai
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from counsellor_fakes import FakeClient
from models.counsellor import LLM_UNREACHABLE_ANSWER, PROVIDER_REJECTED_ANSWER, generate_answer

BUNDLE = {
    "mode": "structured",
    "records": [
        {
            "college_id": "indian-institute-of-technology-bombay",
            "year": 2025,
            "field": "predicted_closing_rank",
            "value": 7445,
            "label": "Computer Science and Engineering predicted closing rank",
        }
    ],
    "college_ids": ["indian-institute-of-technology-bombay"],
    "student_inputs": {"jee_rank": 5000},
}
QUESTION = "What is the closing rank for CSE at IIT Bombay?"
REQUEST = httpx.Request("POST", "http://llm.test/v1/chat/completions")


def _rejection(error_class, status):
    return error_class("provider refused the request", response=httpx.Response(status, request=REQUEST), body=None)


@pytest.mark.parametrize(
    "error",
    [_rejection(openai.APIStatusError, 413), _rejection(openai.RateLimitError, 429)],
    ids=["413", "429"],
)
def test_provider_rejection_gets_its_own_fixed_answer(monkeypatch, error):
    monkeypatch.setattr("models.counsellor._client", lambda: FakeClient([error]))

    result = generate_answer(QUESTION, BUNDLE)

    assert result["answer"] == PROVIDER_REJECTED_ANSWER
    assert result["answer"] != LLM_UNREACHABLE_ANSWER
    assert not re.search(r"\d", result["answer"])
    assert result["error"] is not None
    assert result["blocked_ungrounded_figure"] is False
    assert result["source_college_ids"] == BUNDLE["college_ids"]


def test_rejection_during_the_retry_still_strips_the_first_answer(monkeypatch):
    """Only the first call decides between the two fixed answers. If the
    stricter retry is refused, the first answer is already in hand: its
    ungrounded figure is stripped and the rest is returned, as before.
    """
    first = "The predicted closing rank is 99999 for 2025."
    retry_error = _rejection(openai.RateLimitError, 429)
    monkeypatch.setattr("models.counsellor._client", lambda: FakeClient([first, retry_error]))

    result = generate_answer(QUESTION, BUNDLE)

    assert result["answer"] == "The predicted closing rank is [figure not available in the system's data] for 2025."
    assert result["blocked_ungrounded_figure"] is True


def test_connection_error_still_reads_as_unreachable(monkeypatch):
    error = openai.APIConnectionError(request=REQUEST)
    monkeypatch.setattr("models.counsellor._client", lambda: FakeClient([error]))

    result = generate_answer(QUESTION, BUNDLE)

    assert result["answer"] == LLM_UNREACHABLE_ANSWER
    assert not re.search(r"\d", result["answer"])
    assert result["error"] is not None
