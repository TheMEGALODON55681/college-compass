"""Two ways a figure of the wrong branch used to pass the attribution check.

A branch whose official name holds full stops ("B. Tech. (CSE) and M.Tech in
CSE") was cut into pieces by the sentence splitter, so the figure landed in a
segment that no longer named a branch and the check fell back to "any branch".
And a college whose name holds a branch name ("Indian Institute of Information
Technology Bhopal") counted as naming that branch, so a Computer Science figure
stated with the Information Technology value passed. Each case states another
branch's real closing rank beside the branch it names; the faithful twin must
still pass.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.counsellor import validate_grounding
from models.counsellor_retrieval import build_context_bundle
from test_counsellor_out_of_reach import _state

SENTENCE = "In {year}, the {category} closing rank for {branch} at {name} was {value}."


def _college_name(college_id):
    colleges = _state()["counsellor_lookup"]["colleges"]
    return colleges.loc[colleges["college_id"] == college_id, "canonical_name"].iloc[0]


def _bundle_and_rows(college_id):
    bundle = build_context_bundle(f"closing ranks for {_college_name(college_id)}", None, _state())
    rows = [r for r in bundle["records"] if r["field"] == "actual_closing_rank" and r["category"] == "OPEN"]
    assert rows, college_id
    return bundle, rows


def _states(bundle, row, other, college_id):
    kwargs = {"year": row["year"], "category": row["category"], "branch": row["branch"], "name": _college_name(college_id)}
    wrong = SENTENCE.format(value=other["value"], **kwargs)
    right = SENTENCE.format(value=row["value"], **kwargs)
    return wrong, right, str(other["value"])


def _pick(rows, branch_ok):
    for row in rows:
        if not branch_ok(row["branch"]):
            continue
        own = {r["value"] for r in rows if r["branch"] == row["branch"]}
        for other in rows:
            if other["branch"] != row["branch"] and other["value"] not in own:
                return row, other
    raise AssertionError("no pair of branches with different closing ranks: the test would prove nothing")


def test_branch_name_with_full_stops_is_one_name():
    college_id = "indian-institute-of-technology-patna"
    bundle, rows = _bundle_and_rows(college_id)
    row, other = _pick(rows, lambda b: b == "B. Tech. (CSE) and M.Tech in CSE")
    wrong, right, wrong_value = _states(bundle, row, other, college_id)

    assert wrong_value in validate_grounding(wrong, bundle)
    assert validate_grounding(right, bundle) == []


def test_every_dotted_branch_name_keeps_its_figure_attributed():
    """One wrong-branch case for every college that has a branch whose name holds
    a full stop (the Phase 3 sweep found 144 such sentences). At least three must
    be checked, so a splitter that breaks inside a name cannot pass unnoticed.
    """
    colleges = _state()["counsellor_lookup"]["colleges"]
    checked = 0
    for college_id in colleges["college_id"]:
        bundle = build_context_bundle(f"closing ranks for {_college_name(college_id)}", None, _state())
        rows = [r for r in bundle["records"] if r["field"] == "actual_closing_rank" and r["category"] == "OPEN"]
        if not any("." in r["branch"] for r in rows):
            continue
        try:
            row, other = _pick(rows, lambda b: "." in b)
        except AssertionError:
            continue
        wrong, right, wrong_value = _states(bundle, row, other, college_id)
        assert wrong_value in validate_grounding(wrong, bundle), (college_id, row["branch"])
        assert validate_grounding(right, bundle) == [], (college_id, row["branch"])
        checked += 1
    assert checked >= 3, "too few colleges with a dotted branch name: the test would prove nothing"


def test_college_name_that_holds_a_branch_name_does_not_name_the_branch():
    """Colleges named "Indian Institute of Information Technology ..." that also
    offer an Information Technology branch. Another branch's sentence carrying
    Information Technology's rank must not pass because the college name holds
    those words.
    """
    checked = 0
    for college_id in (
        "indian-institute-of-information-technology-allahabad",
        "indian-institute-of-information-technology-lucknow",
        "indian-institute-of-information-technology-iiit-una-himachal-pradesh",
        "international-institute-of-information-technology-bhubaneswar",
    ):
        bundle, rows = _bundle_and_rows(college_id)
        it_rows = [r for r in rows if r["branch"] == "Information Technology"]
        if not it_rows:
            continue
        it_row = it_rows[0]
        others = [
            r
            for r in rows
            if r["branch"] != "Information Technology" and it_row["value"] not in {x["value"] for x in rows if x["branch"] == r["branch"]}
        ]
        if not others:
            continue
        wrong, right, wrong_value = _states(bundle, others[0], it_row, college_id)
        assert wrong_value in validate_grounding(wrong, bundle), college_id
        assert validate_grounding(right, bundle) == [], college_id
        checked += 1
    assert checked >= 1, "no college to compare: the test would prove nothing"


def test_college_name_with_full_stops_is_one_name():
    """"Dr. B R Ambedkar National Institute of Technology, Jalandhar" was cut at
    "Dr.", so the figure after the name landed in a segment that named no college
    and no branch, and the check fell back to "any branch of any college".
    """
    college_id = "dr-b-r-ambedkar-national-institute-of-technology-jalandhar"
    bundle, rows = _bundle_and_rows(college_id)
    row, other = _pick(rows, lambda b: True)
    wrong, right, wrong_value = _states(bundle, row, other, college_id)

    assert wrong_value in validate_grounding(wrong, bundle)
    assert validate_grounding(right, bundle) == []
