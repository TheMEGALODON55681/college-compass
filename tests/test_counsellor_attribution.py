"""Grounding checks a stated number against the record it belongs to, not
against every value in the bundle. The validator reads which college, year,
category, round, seat pool and kind of figure (closing rank, NIRF rank, fee,
probability) the answer attaches a number to, and the number must be a value
of a record that agrees on each of those the answer states. What the answer
leaves unstated is not checked.

Every wrong case has a twin that states the same sentence correctly and must
come back clean, so a rule that flags too much fails here too.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api.main as main_module
from api.eligibility import load_reference_tables
from counsellor_fakes import FakeClient
from models.counsellor import generate_answer, validate_grounding
from models.counsellor_retrieval import build_context_bundle, build_lookup_cache
from test_memory_fit_regression import _client

DELHI = "indian-institute-of-technology-delhi"
BOMBAY = "indian-institute-of-technology-bombay"
PATNA = "indian-institute-of-technology-patna"
GENDER_NEUTRAL = "Gender-Neutral"
PLACEHOLDER = "[figure not available in the system's data]"


def _legacy(college_id, value, field="actual_closing_rank", year=2024):
    """A record as the bundle carried it before attribution: no program,
    category, quota, pool or round.
    """
    return {"college_id": college_id, "year": year, "field": field, "value": value, "label": "closing rank"}


def _rank(college_id, value, category="OPEN", year=2024, round_=None, branch="Computer Science and Engineering"):
    return {
        "college_id": college_id,
        "year": year,
        "field": "actual_closing_rank",
        "value": value,
        "label": f"{branch} actual JoSAA closing rank {year}, quota AI, category {category}",
        "program_id": branch.lower().replace(" ", "-"),
        "branch": branch,
        "category": category,
        "quota": "AI",
        "pool": GENDER_NEUTRAL,
        "round": round_,
    }


def _nirf(college_id, value):
    return {"college_id": college_id, "year": None, "field": "nirf_rank", "value": value, "label": "latest NIRF rank"}


def _bundle(records):
    ids = list(dict.fromkeys(r["college_id"] for r in records))
    aliases = {DELHI: ["iit delhi"], BOMBAY: ["iit bombay"], PATNA: ["iit patna"]}
    return {
        "mode": "mixed",
        "records": records,
        "college_ids": ids,
        "college_aliases": {i: aliases[i] for i in ids},
        "student_inputs": {"jee_rank": 5000},
    }


def _two_college_bundle():
    return _bundle(
        [
            _rank(DELHI, 116),
            _rank(DELHI, 224, category="OBC-NCL"),
            _rank(DELHI, 175, branch="Mechanical Engineering"),
            _nirf(DELHI, 2),
            _rank(BOMBAY, 68),
            _nirf(BOMBAY, 3),
            _rank(PATNA, 150, year=2023, round_=1),
            _rank(PATNA, 90, year=2023, round_=6),
        ]
    )


def test_college_a_rank_stated_as_college_b_fails_on_the_old_record_shape():
    """The flat-pool bug itself, on records without any attribution fields:
    116 is a real closing rank, but Delhi's, and the answer gives it to Bombay.
    """
    bundle = _bundle([_legacy(DELHI, 116), _legacy(BOMBAY, 68)])

    assert validate_grounding(f"{BOMBAY} has a closing rank of 116.", bundle) == ["116"]
    assert validate_grounding(f"{DELHI} has a closing rank of 116.", bundle) == []


@pytest.mark.parametrize(
    "wrong, right, flagged",
    [
        (
            "At IIT Bombay the OPEN closing rank was 116 in 2024.",
            "At IIT Delhi the OPEN closing rank was 116 in 2024.",
            ["116"],
        ),
        (
            "At IIT Delhi the OPEN closing rank in 2023 was 116.",
            "At IIT Delhi the OPEN closing rank in 2024 was 116.",
            ["116"],
        ),
        (
            "At IIT Delhi the OBC-NCL closing rank was 116 in 2024.",
            "At IIT Delhi the OBC-NCL closing rank was 224 in 2024.",
            ["116"],
        ),
        (
            "At IIT Patna the OPEN closing rank in 2023 was 90 in round 1.",
            "At IIT Patna the OPEN closing rank in 2023 was 90 in round 6.",
            ["90"],
        ),
        (
            "At IIT Delhi the OPEN closing rank for Mechanical Engineering was 116 in 2024.",
            "At IIT Delhi the OPEN closing rank for Mechanical Engineering was 175 in 2024.",
            ["116"],
        ),
        (
            "IIT Delhi's closing rank is 68; IIT Bombay's closing rank is 116.",
            "IIT Delhi's closing rank is 116; IIT Bombay's closing rank is 68.",
            ["68", "116"],
        ),
        (
            "The OPEN closing rank is 224; the OBC-NCL closing rank is 116.",
            "The OPEN closing rank is 116; the OBC-NCL closing rank is 224.",
            ["224", "116"],
        ),
        ("IIT Delhi's NIRF rank is 116.", "IIT Delhi's NIRF rank is 2.", ["116"]),
        ("IIT Delhi's closing rank is 2.", "IIT Delhi's closing rank is 116.", ["2"]),
        (
            "At IIT Delhi the Female-only OPEN closing rank was 116 in 2024.",
            "At IIT Delhi the Gender-Neutral OPEN closing rank was 116 in 2024.",
            ["116"],
        ),
    ],
    ids=[
        "wrong-college",
        "wrong-year",
        "wrong-category",
        "wrong-round",
        "wrong-branch",
        "swapped-colleges",
        "swapped-categories",
        "wrong-kind-nirf",
        "wrong-kind-closing",
        "wrong-pool",
    ],
)
def test_misattributed_figure_fails_and_the_correct_statement_passes(wrong, right, flagged):
    bundle = _two_college_bundle()

    assert validate_grounding(wrong, bundle) == flagged
    assert validate_grounding(right, bundle) == []


def test_a_round_no_record_has_is_flagged_with_its_figure():
    bundle = _two_college_bundle()

    flagged = validate_grounding("At IIT Patna the OPEN closing rank in 2023 was 90 in round 3.", bundle)

    assert flagged == ["90", "3"]


def test_figures_in_separate_sentences_are_judged_separately():
    bundle = _two_college_bundle()
    answer = "IIT Delhi has a closing rank of 116. IIT Bombay has a closing rank of 116."

    assert validate_grounding(answer, bundle) == ["116"]


def test_fallback_when_the_answer_names_no_college_uses_every_college_in_the_bundle():
    """No college in the sentence, so the figure may come from any college the
    bundle covers. The kind of figure is still read where the sentence gives it.
    """
    bundle = _two_college_bundle()

    assert validate_grounding("The closing rank is 116.", bundle) == []
    assert validate_grounding("A figure of 68 appears in the records.", bundle) == []
    assert validate_grounding("The NIRF rank is 3.", bundle) == []
    assert validate_grounding("The NIRF rank is 116.", bundle) == ["116"]


def test_a_cue_word_is_read_for_the_figure_it_sits_beside_not_its_neighbour():
    """224 has no cue word of its own. The NIRF cue after it belongs to the 2
    that follows, and the closing-rank cue before the 116 belongs to 116.
    """
    bundle = _two_college_bundle()

    assert validate_grounding("At IIT Delhi the closing ranks are OPEN 116, OBC-NCL 224, and its NIRF rank is 2.", bundle) == []
    assert validate_grounding("The NIRF rank of IIT Delhi is 2, and 116 is its OPEN closing rank.", bundle) == []
    assert validate_grounding("At IIT Delhi the closing ranks are OPEN 116, OBC-NCL 224, and its NIRF rank is 116.", bundle) == ["116"]


def test_a_figure_in_a_later_clause_does_not_hide_this_figures_right_hand_cue():
    """The cue after a figure is read when no figure follows it in its own
    segment. A figure in the next clause is another segment's business.
    """
    bundle = _two_college_bundle()

    assert validate_grounding("IIT Delhi has 116 as its NIRF rank; IIT Delhi has closing rank 116.", bundle) == ["116"]
    assert validate_grounding("IIT Delhi has 2 as its NIRF rank; IIT Delhi has closing rank 116.", bundle) == []


def _nested_branch_bundle():
    ai = "Computer Science and Engineering (Artificial Intelligence)"
    return _bundle(
        [
            _rank(DELHI, 116),
            _rank(DELHI, 300, branch=ai),
            _rank(DELHI, 2221, branch="Chemical Engineering"),
            _rank(DELHI, 4849, branch="Biotechnology and Biochemical Engineering"),
        ]
    )


@pytest.mark.parametrize(
    "wrong, right, flagged",
    [
        (
            "At IIT Delhi, Biotechnology and Biochemical Engineering OPEN closing rank was 2221 in 2024.",
            "At IIT Delhi, Biotechnology and Biochemical Engineering OPEN closing rank was 4849 in 2024.",
            ["2221"],
        ),
        (
            "At IIT Delhi, Chemical Engineering OPEN closing rank was 4849 in 2024.",
            "At IIT Delhi, Chemical Engineering OPEN closing rank was 2221 in 2024.",
            ["4849"],
        ),
        (
            "At IIT Delhi the OPEN closing rank for Computer Science and Engineering (Artificial Intelligence) was 116 in 2024.",
            "At IIT Delhi the OPEN closing rank for Computer Science and Engineering (Artificial Intelligence) was 300 in 2024.",
            ["116"],
        ),
        (
            "At IIT Delhi the OPEN closing rank for Computer Science and Engineering was 300 in 2024.",
            "At IIT Delhi the OPEN closing rank for Computer Science and Engineering was 116 in 2024.",
            ["300"],
        ),
    ],
    ids=["name-inside-a-word", "shorter-name-in-longer-bundle", "name-inside-a-longer-name", "longer-name-in-bundle"],
)
def test_a_branch_name_inside_a_longer_branch_name_is_not_a_mention_of_the_short_one(wrong, right, flagged):
    bundle = _nested_branch_bundle()

    assert validate_grounding(wrong, bundle) == flagged
    assert validate_grounding(right, bundle) == []


def test_two_branches_named_on_their_own_are_both_read():
    bundle = _nested_branch_bundle()
    answer = "At IIT Delhi the OPEN closing rank was 2221 for Chemical Engineering and 4849 for Biotechnology and Biochemical Engineering."

    assert validate_grounding(answer, bundle) == []


def test_a_cue_word_stays_inside_its_table_cell():
    """Found live: a table row "| IIT Patna | (no NIRF rank in the records) | 2.5 |"
    for a college with a fee and no NIRF rank. The NIRF cue sits in the empty rank
    cell, not beside the fee, so the fee must not be read as a NIRF rank.
    """
    fees = {"college_id": PATNA, "year": None, "field": "fees_annual_lakhs", "value": 2.5, "label": "fees"}
    delhi_fees = {**fees, "college_id": DELHI}
    bundle = _bundle([_nirf(DELHI, 2), delhi_fees, fees])
    table = "| IIT Delhi | 2 | 2.5 |\n| IIT Patna | none (no NIRF rank in the records) | 2.5 |"

    assert validate_grounding(table, bundle) == []
    assert validate_grounding("| IIT Delhi | NIRF rank 2.5 |", bundle) == ["2.5"]


def test_a_figure_in_no_record_is_still_flagged():
    bundle = _two_college_bundle()

    assert validate_grounding("At IIT Delhi the OPEN closing rank was 9999 in 2024.", bundle) == ["9999"]


def test_the_students_own_rank_is_not_attributed():
    bundle = _two_college_bundle()

    assert validate_grounding("With your rank of 5000, IIT Delhi (closing rank 116) is within reach.", bundle) == []


def test_misattributed_first_answer_is_retried_and_the_corrected_answer_returned(monkeypatch):
    first = "At IIT Bombay the OPEN closing rank was 116 in 2024."
    corrected = "At IIT Bombay the OPEN closing rank was 68 in 2024."
    client = FakeClient([first, corrected])
    monkeypatch.setattr("models.counsellor._client", lambda: client)

    result = generate_answer("What is the closing rank at IIT Bombay?", _two_college_bundle())

    assert result["answer"] == corrected
    assert result["blocked_ungrounded_figure"] is False
    assert "116" in client.calls[1][-1]["content"]


def test_misattributed_figure_that_survives_the_retry_is_stripped(monkeypatch):
    answer = "At IIT Bombay the OPEN closing rank was 116 in 2024."
    monkeypatch.setattr("models.counsellor._client", lambda: FakeClient([answer, answer]))

    result = generate_answer("What is the closing rank at IIT Bombay?", _two_college_bundle())

    assert result["answer"] == f"At IIT Bombay the OPEN closing rank was {PLACEHOLDER} in 2024."
    assert result["blocked_ungrounded_figure"] is True


@pytest.fixture(scope="module")
def state():
    return {"counsellor_lookup": build_lookup_cache(), "reference_tables": load_reference_tables()}


def test_history_records_carry_their_attribution(state):
    bundle = build_context_bundle("closing ranks for IIT Delhi", None, state)

    ranks = [r for r in bundle["records"] if r["field"] == "actual_closing_rank"]
    assert ranks
    for r in ranks:
        assert r["pool"] == GENDER_NEUTRAL
        assert r["quota"] == "AI"
        assert r["program_id"] and r["category"]
        assert "round" in r
    assert "iit delhi" in bundle["college_aliases"][DELHI]


def test_forecast_records_carry_their_attribution():
    _client()  # boots the app once for the whole session
    profile = {"jee_rank": 30000, "category": "OPEN", "home_state": "Delhi"}

    bundle = build_context_bundle("closing rank for computer science at IIIT Agartala", profile, main_module.model_state)

    forecast = [r for r in bundle["records"] if r["field"] in {"predicted_closing_rank", "band", "admission_probability"}]
    assert {r["field"] for r in forecast} == {"predicted_closing_rank", "band", "admission_probability"}
    for r in forecast:
        assert r["category"] == "OPEN"
        assert r["pool"] == GENDER_NEUTRAL
        assert r["quota"] and r["program_id"]
        assert r["round"] is None


def test_real_history_rows_are_judged_by_their_own_category(state):
    """A rank from the real bundle, written with its own category, passes. The
    same rank written with another category fails.
    """
    bundle = build_context_bundle("closing ranks for IIT Delhi", None, state)
    by_key = {(r["program_id"], r["category"]): r for r in bundle["records"] if r["field"] == "actual_closing_rank"}
    obc_values = {r["value"] for (_, category), r in by_key.items() if category == "OBC-NCL"}
    program = next(p for (p, c), r in by_key.items() if c == "OPEN" and r["value"] not in obc_values and (p, "OBC-NCL") in by_key)
    opened = by_key[(program, "OPEN")]
    sentence = "At IIT Delhi the {category} closing rank was {value} in {year}."

    right = sentence.format(category="OPEN", value=opened["value"], year=opened["year"])
    wrong = sentence.format(category="OBC-NCL", value=opened["value"], year=opened["year"])

    assert validate_grounding(right, bundle) == []
    assert validate_grounding(wrong, bundle) == [str(opened["value"])]
