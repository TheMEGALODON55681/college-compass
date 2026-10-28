"""The retry path under stress: what the caller gets when the stricter second
call comes back wrong, empty or not at all, and that /chat passes the
verification note through only when there is one.
"""

import sys
from pathlib import Path

import httpx
import openai
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from counsellor_fakes import FakeClient
from models.counsellor import generate_answer
from test_counsellor_escalation import BUNDLE, FABRICATED, QUESTION, REQUEST

GOOD = "In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi was 116."
OTHER_BAD = "In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi was 88888."


def _run(monkeypatch, replies):
    client = FakeClient(replies)
    monkeypatch.setattr("models.counsellor._client", lambda: client)
    return generate_answer(QUESTION, BUNDLE), client


def test_a_different_wrong_figure_in_the_retry_is_the_one_stripped(monkeypatch):
    result, client = _run(monkeypatch, [FABRICATED, OTHER_BAD])

    assert len(client.calls) == 2
    assert "88888" not in result["answer"] and "99999" not in result["answer"]
    assert "[figure not available in the system's data]" in result["answer"]
    assert result["verification"]["unverified_count"] == 1


@pytest.mark.parametrize("reply", [None, "", "   "], ids=["none", "empty", "blank"])
def test_retry_with_no_content_strips_the_first_answer(monkeypatch, reply):
    result, _ = _run(monkeypatch, [FABRICATED, reply])

    assert "99999" not in result["answer"] and result["blocked_ungrounded_figure"] is True
    assert result["verification"]["outcome"] == "escalate"


def test_the_retry_is_made_once_and_only_once(monkeypatch):
    result, client = _run(monkeypatch, [FABRICATED, OTHER_BAD, GOOD])

    assert len(client.calls) == 2
    assert result["blocked_ungrounded_figure"] is True


def test_retry_carries_the_first_answer_and_a_correction(monkeypatch):
    _, client = _run(monkeypatch, [FABRICATED, GOOD])

    retry = client.calls[1]
    assert retry[-2] == {"role": "assistant", "content": FABRICATED}
    assert "99999" in retry[-1]["content"]


def test_first_answer_with_two_bad_figures_reports_the_count(monkeypatch):
    two = "The OPEN closing ranks for Computer Science and Engineering at IIT Delhi were 99999 and 88888 in 2024."
    result, _ = _run(monkeypatch, [two, two])

    assert result["verification"]["unverified_count"] == 2
    assert "99999" not in result["answer"] and "88888" not in result["answer"]


def test_chat_returns_the_note_only_when_a_figure_was_stripped(monkeypatch):
    from test_memory_fit_regression import _client as app_client

    client = app_client()
    question = "What is the closing rank for Computer Science at IIT Delhi?"
    replies = ["I do not know."]
    fake = FakeClient(replies)
    monkeypatch.setattr("models.counsellor._client", lambda: fake)
    plain = client.post("/chat", json={"question": question}).json()
    assert "verification" not in plain

    fake = FakeClient(["In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi was 99999."] * 2)
    monkeypatch.setattr("models.counsellor._client", lambda: fake)
    escalated = client.post("/chat", json={"question": question}).json()

    note = escalated["verification"]
    assert escalated["blocked_ungrounded_figure"] is True and "99999" not in escalated["answer"]
    assert note["outcome"] == "escalate"
    assert note["closest"]["college_id"] == "indian-institute-of-technology-delhi"
    assert note["closest"]["branch"] == "Computer Science and Engineering"
    assert {"program", "category", "pool", "year", "round", "value", "kind"} <= set(note["closest"])
