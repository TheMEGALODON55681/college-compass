"""The three-arm evaluation harness (models/eval_counsellor.py): the
evaluation-only switches on generate_answer, that the API never passes them,
and the harness's own scoring over scripted completions (no provider, no
database). Each arm sees the same completions, so a question costs one provider
call, plus one more only when the first answer is rejected.
"""

import json
import sys
from pathlib import Path

import httpx
import openai
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from counsellor_fakes import FakeClient
from models import eval_counsellor as ev
from models.counsellor import PLACEMENT_DECLINE_ANSWER, generate_answer
from test_counsellor_escalation import BUNDLE, CSE, DELHI, FABRICATED, QUESTION, REQUEST, _bundle, _rank

GOOD = "In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi was 116."
CLOSEST = {
    "college_id": DELHI,
    "branch": CSE,
    "program": "4-year Bachelor of Technology",
    "category": "OPEN",
    "pool": "Gender-Neutral",
    "year": 2024,
    "round": None,
    "kind": "actual_closing_rank",
    "value": 116,
}


def _question(closest, class_="near_miss"):
    return {"id": "T01", "class": class_, "question": QUESTION, "student_profile": None, "closest_figures": closest}


def _run(replies, question=None, bundle=BUNDLE):
    client = FakeClient(replies)
    record = ev.run_question(question or _question([CLOSEST]), bundle, client, ev.Pacer(0))
    return record, client


# --- the switches ----------------------------------------------------------------------------


def test_validator_off_returns_the_first_answer_as_it_came(monkeypatch):
    client = FakeClient([FABRICATED])
    monkeypatch.setattr("models.counsellor._client", lambda: client)
    result = generate_answer(QUESTION, BUNDLE, validate=False)

    assert result["answer"] == FABRICATED and result["blocked_ungrounded_figure"] is False
    assert len(client.calls) == 1 and "verification" not in result


def test_escalation_off_strips_without_a_note(monkeypatch):
    client = FakeClient([FABRICATED, FABRICATED])
    monkeypatch.setattr("models.counsellor._client", lambda: client)
    result = generate_answer(QUESTION, BUNDLE, escalate=False)

    assert "99999" not in result["answer"] and result["blocked_ungrounded_figure"] is True
    assert len(client.calls) == 2 and "verification" not in result


def test_the_api_never_passes_the_switches(monkeypatch):
    from test_memory_fit_regression import _client as app_client

    calls = []

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return {"answer": "ok", "source_college_ids": [], "blocked_ungrounded_figure": False, "error": None}

    monkeypatch.setattr("api.main.generate_answer", spy)
    app_client().post("/chat", json={"question": QUESTION})

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert len(args) == 2 and kwargs == {}


# --- the arms over shared completions ----------------------------------------------------------


def test_a_rejected_first_answer_splits_the_arms_over_one_retry():
    record, client = _run([FABRICATED, FABRICATED])

    assert len(client.calls) == 2 and record["provider_calls"] == 2
    assert record["first_rejected"] is True
    assert {arm: r["outcome"] for arm, r in record["arms"].items()} == {"A": "unvalidated", "B": "stripped", "C": "closest"}
    assert {arm: r["useful"] for arm, r in record["arms"].items()} == {"A": False, "B": False, "C": True}
    assert record["arms"]["A"]["unsupported"] is True
    assert not record["arms"]["B"]["unsupported"] and not record["arms"]["C"]["unsupported"]


def test_a_clean_first_answer_costs_one_call_and_is_clean_in_every_arm():
    record, client = _run([GOOD])

    assert len(client.calls) == 1 and record["first_rejected"] is False
    assert {r["outcome"] for r in record["arms"].values()} == {"clean"}
    assert all("useful" not in r for r in record["arms"].values())


def test_a_retry_that_fixes_the_answer_is_recovered_not_escalated():
    record, _ = _run([FABRICATED, GOOD])

    assert record["arms"]["B"]["outcome"] == "recovered" and record["arms"]["C"]["outcome"] == "recovered"
    assert record["arms"]["C"]["useful"] is False  # the definition asks for a note, a recovered answer is counted apart


def test_nothing_close_is_useful_only_with_the_note():
    bundle = _bundle(_rank(DELHI, "Mathematics and Computing", 330))
    record, _ = _run([FABRICATED, FABRICATED], _question([]), bundle)

    assert record["arms"]["C"]["outcome"] == "nothing_close" and record["arms"]["C"]["useful"] is True
    assert record["arms"]["B"]["useful"] is False


def test_a_refused_retry_is_a_refusal_in_b_and_c_and_not_useful():
    refusal = openai.RateLimitError("rate limited", response=httpx.Response(429, request=REQUEST), body=None)
    record, client = _run([FABRICATED, refusal])

    assert len(client.calls) == 2
    assert record["arms"]["B"]["outcome"] == "refused_retry" and record["arms"]["C"]["outcome"] == "refused_retry"
    assert record["arms"]["C"]["useful"] is False and record["arms"]["C"]["answered"] is False


def test_a_refused_first_call_is_unscored_and_not_a_rejection():
    refusal = openai.RateLimitError("rate limited", response=httpx.Response(429, request=REQUEST), body=None)
    record, _ = _run([refusal])

    assert record["first_rejected"] is None
    assert {r["outcome"] for r in record["arms"].values()} == {"refused_first"}


def test_a_connection_failure_is_not_a_result():
    with pytest.raises(ev.ProviderUnreachable):
        _run([openai.APIConnectionError(request=REQUEST)])


def test_a_retry_failure_that_is_not_a_refusal_is_not_a_result():
    for fault in (openai.APIConnectionError(request=REQUEST), openai.InternalServerError("boom", response=httpx.Response(500, request=REQUEST), body=None)):
        with pytest.raises(ev.ProviderUnreachable):
            _run([FABRICATED, fault])


def test_the_daily_limit_stops_the_run_and_a_per_minute_limit_does_not():
    daily = openai.RateLimitError("Rate limit reached on tokens per day (TPD)", response=httpx.Response(429, request=REQUEST), body=None)
    with pytest.raises(ev.DailyLimit):
        _run([daily])
    _run([openai.RateLimitError("Rate limit reached on tokens per minute (TPM)", response=httpx.Response(429, request=REQUEST), body=None)])


def test_placement_makes_no_call_and_stays_the_fixed_refusal():
    bundle = {"mode": "out_of_scope_placement", "records": [], "college_ids": [], "student_inputs": {}}
    record, client = _run([], _question([], "placement"), bundle)

    assert client.calls == [] and record["provider_calls"] == 0
    assert {r["outcome"] for r in record["arms"].values()} == {"placement_decline"}
    assert record["answers"]["C"]["answer"] == PLACEMENT_DECLINE_ANSWER


# --- the report --------------------------------------------------------------------------------


def test_summary_counts_per_class_and_reports_the_separate_question_apart():
    rejected, _ = _run([FABRICATED, FABRICATED])
    clean, _ = _run([GOOD])
    clean["id"] = "T02"
    clean["class"] = "verifiable"
    v10, _ = _run([FABRICATED, FABRICATED])
    v10["id"] = "V10"
    v10["class"] = "verifiable"
    placement, _ = _run([], _question([], "placement"), {"mode": "out_of_scope_placement", "records": [], "college_ids": [], "student_inputs": {}})
    placement["id"] = "P01"
    summary = ev.summarize([rejected, clean, v10, placement])

    assert summary["tables"]["C"]["near_miss"]["useful"] == [1, 1]
    assert summary["tables"]["A"]["near_miss"]["unsupported"] == [1, 1]
    assert summary["tables"]["A"]["verifiable"]["questions"] == 1  # V10 is not in its class
    assert summary["tables"]["A"]["overall"]["questions"] == 2  # placement has its own row and is not in the total
    assert summary["tables"]["A"]["placement"]["questions"] == 1
    assert summary["reported_apart"]["V10"]["C"]["outcome"] == "closest"
    assert "Useful after rejection" in ev.render(summary)


def test_the_question_set_is_the_hashed_one():
    assert len(ev.verify_question_set()) == 44


# --- the run file and the report -----------------------------------------------------------------


def test_a_run_file_cut_off_mid_line_loses_only_that_line(tmp_path):
    path = tmp_path / "run.jsonl"
    path.write_text('{"id": "V01"}\n{"id": "V02"}\n{"id": "V03", "cla', encoding="utf-8")
    assert set(ev._load_done(path)) == {"V01", "V02"}

    path.write_text('{"id": "V01"}\n{"id": "V0\n{"id": "V03"}\n', encoding="utf-8")
    with pytest.raises(ValueError):  # a damaged line in the middle is not a crash mid-write
        ev._load_done(path)


def test_report_will_not_overwrite_the_results_with_nothing(tmp_path, monkeypatch):
    results = tmp_path / "results.json"
    results.write_text("kept", encoding="utf-8")
    monkeypatch.setattr(ev, "RESULTS_PATH", results)

    with pytest.raises(SystemExit):
        ev.report(tmp_path / "no-such-run.jsonl")
    assert results.read_text(encoding="utf-8") == "kept"


def test_category_and_college_are_matched_as_whole_words():
    figure = {**CLOSEST, "category": "SC"}
    text = "Indian Institute of Technology Delhi, Computer Science and Engineering (four-year BTech), Gender-Neutral seats, 2024, no round data."
    assert not ev._states_fields(text, figure, BUNDLE)  # "sc" is inside "Science" and "OPEN" is not SC
    assert ev._states_fields(text.replace("Delhi,", "Delhi, SC,"), figure, BUNDLE)

    open_text = text.replace("Delhi,", "Delhi, OPEN,")
    assert ev._states_fields(open_text, CLOSEST, BUNDLE)
    assert not ev._states_fields(open_text.replace("OPEN,", "OPEN (PwD),"), CLOSEST, BUNDLE)  # another category
    assert not ev._states_fields(open_text.replace("2024", "120245"), CLOSEST, BUNDLE)  # a year is not part of a rank


def test_recorded_completions_score_the_same_as_the_live_ones():
    live, _ = _run([FABRICATED, FABRICATED])
    again = ev.run_question(_question([CLOSEST]), BUNDLE, ev.Stored(live["completions"]), ev.Pacer(0))
    refused, _ = _run([FABRICATED, openai.RateLimitError("rate limited", response=httpx.Response(429, request=REQUEST), body=None)])
    refused_again = ev.run_question(_question([CLOSEST]), BUNDLE, ev.Stored(refused["completions"]), ev.Pacer(0))

    assert again["arms"] == live["arms"] and again["completions"] == live["completions"]
    assert refused_again["arms"] == refused["arms"]


def test_rescoring_keeps_the_recording_and_refuses_what_it_cannot_cover():
    question = _question([CLOSEST])
    live, _ = _run([FABRICATED, FABRICATED])
    assert ev._rescored(question, BUNDLE, live)["completions"] == live["completions"]

    blank, _ = _run([FABRICATED, ""])  # a blank retry is recorded as blank, not as a refusal
    assert blank["completions"] == [FABRICATED, ""]
    assert ev._rescored(question, BUNDLE, blank)["arms"] == blank["arms"]

    with pytest.raises(SystemExit):  # the code now wants a retry that was never recorded
        ev._rescored(question, BUNDLE, {**live, "completions": [FABRICATED]})
    with pytest.raises(SystemExit):  # the code now needs fewer completions than were recorded
        ev._rescored(question, BUNDLE, {**live, "completions": [GOOD, FABRICATED]})


def test_report_wants_records_scored_by_the_current_code(tmp_path, monkeypatch):
    results = tmp_path / "results.json"
    monkeypatch.setattr(ev, "RESULTS_PATH", results)
    run = tmp_path / "run.jsonl"
    record, _ = _run([GOOD])
    run.write_text(json.dumps({**record, "scored_by": "another"}) + "\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        ev.report(run)
    assert not results.exists()


def test_the_pacer_waits_out_the_rest_of_the_delay(monkeypatch):
    slept = []
    monkeypatch.setattr(ev.time, "sleep", slept.append)
    ev.Pacer(60).wait()

    assert 59 < slept[0] <= 60
