"""Every rank the counsellor can cite must carry college, branch (with the
program), category, seat pool, year and round (Rules.md section 6). The model
reads the context lines, so the six fields are tested on the lines
`_format_context` prints, for history rows and forecast rows alike. IIT Delhi
lists the same branch name for a 4-year B.Tech and a 5-year dual degree: their
lines must read differently.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from counsellor_fakes import FakeClient
from models.counsellor import _format_context, generate_answer
from models.counsellor_retrieval import _program_tag, build_context_bundle
from test_counsellor_out_of_reach import IN_REACH, IIT_DELHI, _state

ADMISSION_FIELDS = {"actual_closing_rank", "predicted_closing_rank", "band", "admission_probability"}
MAX_PROMPT_TOKENS = 7000
CHARS_PER_TOKEN = 3.4


def _admission_lines(bundle):
    lines = _format_context(bundle).split("\n")
    pairs = [(r, line) for r, line in zip(bundle["records"], lines)]
    return [(r, line) for r, line in pairs if r["field"] in ADMISSION_FIELDS]


def _assert_six_fields(record, line):
    assert record["college_id"] in line
    assert record["branch"] in line
    assert record["program"] in line
    assert record["category"] in line
    assert record["pool"] in line
    assert str(record["year"]) in line
    round_text = f"round {record['round']}" if record["round"] is not None else "no round data"
    assert round_text in line


@pytest.mark.parametrize(
    "question,profile",
    [
        ("What is the closing rank for Computer Science at IIT Delhi?", None),
        ("What is the closing rank for Computer Science at IIT Delhi?", IN_REACH),
        ("closing ranks for IIT Patna", None),
        ("closing ranks for NIT Trichy", None),
    ],
)
def test_every_admission_figure_carries_the_six_fields(question, profile):
    bundle = build_context_bundle(question, profile, _state())
    lines = _admission_lines(bundle)

    assert lines, "no admission figure in the bundle: the test would prove nothing"
    for record, line in lines:
        _assert_six_fields(record, line)


def test_history_and_forecast_both_appear_for_a_student_in_reach():
    bundle = build_context_bundle("What is the closing rank for Computer Science at IIT Delhi?", IN_REACH, _state())

    assert {r["field"] for r, _ in _admission_lines(bundle)} == ADMISSION_FIELDS


def test_two_programs_with_one_branch_name_read_differently():
    bundle = build_context_bundle("What is the closing rank for Computer Science at IIT Delhi?", None, _state())
    rows = [
        (r, line)
        for r, line in _admission_lines(bundle)
        if r["branch"] == "Computer Science and Engineering" and r["category"] == "OPEN"
    ]

    assert len(rows) == 2, "IIT Delhi should list a 4-year and a 5-year Computer Science row"
    four, five = sorted(rows, key=lambda pair: pair[0]["program_id"])
    assert four[1].split(": ")[0] != five[1].split(": ")[0]
    assert {r["program"] for r, _ in rows} == {"four-year BTech", "five-year dual degree"}


def test_no_two_rank_lines_of_a_bundle_share_a_label():
    for question in ("closing ranks for IIT Delhi", "closing ranks for IIT Patna"):
        bundle = build_context_bundle(question, None, _state())
        labels = [line.split(": ")[0] for _, line in _admission_lines(bundle)]
        assert len(labels) == len(set(labels)), question


def test_program_tag_has_no_digits_and_no_full_stops():
    """The validator reads every digit group in an answer as a figure, so a
    label the model echoes ("4-year") would be flagged as an ungrounded 4. Full
    stops inside a label split a sentence in the answer.
    """
    cases = [
        ("Bachelor of Technology", 4, "four-year BTech"),
        ("Bachelor and Master of Technology (Dual Degree)", 5, "five-year dual degree"),
        ("B.Tech. + M.Tech./MS (Dual Degree)", 5, "five-year dual degree"),
        ("Integrated B. Tech. and M. Tech.", 5, "five-year integrated"),
        ("B. Tech / B. Tech (Hons.)", 4, "four-year B Tech / B Tech (Hons)"),
        ("Bachelor of Architecture", 5, "five-year Bachelor of Architecture"),
    ]
    for degree, years, expected in cases:
        tag = _program_tag(degree, years)
        assert tag == expected
        assert not re.search(r"\d|\.", tag)


def test_every_program_in_the_database_gets_a_clean_tag():
    programs = _state()["reference_tables"][1]
    for row in programs.itertuples(index=False):
        tag = _program_tag(row.degree_type, row.duration_years)
        assert tag and not re.search(r"\d|\.", tag), (row.program_id, tag)


def test_one_college_question_without_a_profile_stays_under_the_provider_limit(monkeypatch):
    """IIT Patna has 149 history rows. Uncapped and with the six-field labels the
    prompt passes 7,000 tokens, so a one-college question is capped like the rest.
    """
    question = "closing ranks for IIT Patna"
    client = FakeClient(["ok"])
    monkeypatch.setattr("models.counsellor._client", lambda: client)
    bundle = build_context_bundle(question, None, _state())
    generate_answer(question, bundle)

    prompt = "".join(m["content"] for m in client.calls[0])
    assert len(prompt) / CHARS_PER_TOKEN < MAX_PROMPT_TOKENS


NON_BREAKING_HYPHEN = chr(0x2011)


@pytest.mark.parametrize(
    "program,value,flagged",
    [
        ("four-year BTech", 116, []),
        ("4-year BTech", 116, []),
        ("five-year dual degree", 204, []),
        (f"5{NON_BREAKING_HYPHEN}year dual degree", 204, []),
        ("four-year BTech", 204, ["204"]),
        (f"4{NON_BREAKING_HYPHEN}year BTech", 204, ["204"]),
        ("five-year dual degree", 116, ["116"]),
        ("dual degree", 116, []),
    ],
)
def test_a_figure_belongs_to_the_program_the_answer_names(program, value, flagged):
    """IIT Delhi's four-year BTech (116) and five-year dual degree (204) share a
    branch name. An answer that names a program is held to that program's row;
    one that names none is not (the same fallback as an unnamed branch).
    """
    from models.counsellor import validate_grounding
    from test_counsellor_escalation import BUNDLE

    text = f"In 2024, the OPEN closing rank for Computer Science and Engineering ({program}) at IIT Delhi was {value}."

    assert validate_grounding(text, BUNDLE) == flagged


@pytest.mark.parametrize(
    "template",
    [
        "For the four-year B.Tech. Computer Science and Engineering at IIT Delhi, the OPEN closing rank in 2024 was {v}.",
        "The 4-year B. Tech OPEN closing rank for Computer Science and Engineering at IIT Delhi in 2024 is {v}.",
        "B.Tech (4-year): OPEN closing rank {v} for Computer Science and Engineering at IIT Delhi in 2024.",
        "In 2024 the OPEN closing rank for Computer Science and Engineering at IIT Delhi, BTech (4 years), was {v}.",
        "**4-year** BTech: the OPEN closing rank for Computer Science and Engineering at IIT Delhi in 2024 was {v}.",
        "In 2024, the OPEN closing rank for Computer Science and Engineering (4-yr BTech) at IIT Delhi was {v}.",
        "In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi, Bachelor of Technology (4 years), was {v}.",
        "In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi, 4-year-BTech, was {v}.",
        "| IIT Delhi | Computer Science and Engineering | BTech | 4 years | OPEN | 2024 | {v} |",
    ],
    ids=["b-tech-full-stop", "b-space-tech", "length-after", "years-plural", "markdown", "yr", "bachelor-of", "hyphens", "table"],
)
def test_the_program_is_read_in_the_ways_a_model_writes_it(template):
    """The same four-year BTech sentence: its own rank (116) is accepted, the dual
    degree's rank (204) is flagged, in the spellings a model uses besides the label's.
    """
    from models.counsellor import validate_grounding
    from test_counsellor_escalation import BUNDLE

    assert validate_grounding(template.format(v=116), BUNDLE) == []
    assert validate_grounding(template.format(v=204), BUNDLE) == ["204"]


NL = chr(10)


def _two_colleges():
    from test_counsellor_escalation import BOMBAY, CSE, DELHI, _bundle, _rank

    return _bundle(_rank(DELHI, CSE, 116), _rank(BOMBAY, CSE, 66))


def test_a_program_mention_does_not_swallow_the_sentence_after_it():
    """A full stop after "BTech" ends the sentence, so what follows is judged on its
    own: the dual degree's rank under a four-year sentence is flagged, a faithful
    answer that goes on to the dual degree is not.
    """
    from models.counsellor import validate_grounding
    from test_counsellor_escalation import BUNDLE

    head = "In 2024 the OPEN closing rank for Computer Science and Engineering at IIT Delhi was"
    assert validate_grounding(f"{head} 204 on the four-year BTech. IIT Delhi also offers a five-year dual degree.", BUNDLE) == ["204"]
    assert validate_grounding(f"{head} 204 on the four-year BTech. On the five-year dual degree it was 116.", BUNDLE) == ["204", "116"]
    assert validate_grounding(f"{head} 116 on the four-year BTech. The dual degree closed at 204.", BUNDLE) == []


def test_a_program_mention_never_joins_the_next_college_or_line():
    """IIT Delhi's 116 stated under IIT Bombay (whose rank is 66) is flagged when a
    sentence or a line ends with the program name.
    """
    from models.counsellor import validate_grounding

    bundle = _two_colleges()
    bombay = "At IIT Bombay, the OPEN closing rank for Computer Science and Engineering in 2024 was 116."

    assert validate_grounding(f"At IIT Delhi, Computer Science and Engineering, the 4-year B.Tech. {bombay}", bundle) == ["116"]
    assert validate_grounding(f"At IIT Delhi, Computer Science and Engineering, the 4-year BTech{NL}{bombay}", bundle) == ["116"]


def test_an_abbreviation_stop_before_a_branch_name_does_not_end_the_sentence():
    from models.counsellor import validate_grounding

    bundle = _two_colleges()
    text = "At IIT Delhi, the B.Tech. Computer Science and Engineering OPEN closing rank in 2024 was 66."

    assert validate_grounding(text, bundle) == ["66"]
    assert validate_grounding(text.replace("66", "116"), bundle) == []


@pytest.mark.parametrize(
    "text",
    [
        "In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi was 116, a gradual 5-year rise.",
        "In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi was 116, an individual 4 years of data.",
        "In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi was 116 for the B.Tech program, 5 years of history.",
    ],
)
def test_a_word_that_only_ends_in_a_program_word_is_not_a_program(text):
    from models.counsellor import validate_grounding
    from test_counsellor_escalation import BUNDLE

    flagged = validate_grounding(text, BUNDLE)

    assert flagged and flagged[0] in ("4", "5") and "116" not in flagged


def test_the_length_of_a_program_does_not_cut_off_the_cue_before_it():
    """"The closing rank ... (4-year BTech) ... was 2" is a closing rank, not the
    college's NIRF rank (also 2): the length digit must not end the stretch in
    which the cue word "closing" is read.
    """
    from models.counsellor import validate_grounding
    from test_counsellor_escalation import BUNDLE, DELHI, _bundle

    nirf = {"college_id": DELHI, "year": None, "field": "nirf_rank", "value": 2, "label": "latest NIRF rank"}
    bundle = _bundle(*BUNDLE["records"], nirf)

    assert validate_grounding("The closing rank at IIT Delhi (4-year BTech) in 2024 was 2.", bundle) == ["2"]
    assert validate_grounding("IIT Delhi's NIRF rank is 2.", bundle) == []


def test_a_look_alike_letter_cannot_crash_the_validator():
    """"f" + dotless i + "ve" matches "five" when the pattern ignores case in Unicode;
    a lookup keyed on the lowered match then raised KeyError out of /chat.
    """
    from models.counsellor import validate_grounding
    from test_counsellor_escalation import BUNDLE

    text = f"In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi, f{chr(0x131)}ve-year dual degree, was 204."

    assert validate_grounding(text, BUNDLE) == []


@pytest.mark.parametrize(
    "tail,figure",
    [("and it has fallen every year for the last 5 years.", "5"), ("a 5-year trend.", "5"), ("over 4 years.", "4")],
)
def test_a_span_of_years_is_still_a_figure(tail, figure):
    """Only a length beside a program word is a program. "5 years" of history is
    a claim the records cannot back (the history is the latest year only).
    """
    from models.counsellor import validate_grounding
    from test_counsellor_escalation import BUNDLE

    text = f"In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi was 116, {tail}"

    assert validate_grounding(text, BUNDLE) == [figure]


def test_a_program_duration_written_in_digits_is_not_a_figure():
    """The labels spell the duration out ("four-year BTech"), and a model rewrites
    it as "4-year" (live check, 2026-10-28). That digit names a program, not a
    rank, so the validator must not flag it and force a retry. A bare 4, or a
    duration no program in the bundle has, is still flagged.
    """
    from test_counsellor_escalation import BUNDLE

    four = "In 2024, the OPEN closing rank for Computer Science and Engineering (4\u2011year BTech) at IIT Delhi was 116."
    five = "In 2024, the OPEN closing rank for Computer Science and Engineering (5-year dual degree) at IIT Delhi was 204."
    from models.counsellor import validate_grounding

    assert validate_grounding(four, BUNDLE) == []
    assert validate_grounding(five, BUNDLE) == []
    assert validate_grounding(four.replace("(4\u2011year BTech)", "(6-year dual degree)"), BUNDLE) == ["6"]
    assert validate_grounding("In 2024, the OPEN closing rank for Computer Science and Engineering at IIT Delhi was 4.", BUNDLE) == ["4"]
