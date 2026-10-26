"""College-name matching in the counsellor: a short alias must resolve to the
college the student named, never to another college whose alias it happens to
sit inside ("iit bhubaneswar" inside "iiit bhubaneswar").
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.counsellor_retrieval import _match_college, build_lookup_cache

IIIT_BHUBANESWAR = "international-institute-of-information-technology-bhubaneswar"
IIT_BHUBANESWAR = "indian-institute-of-technology-bhubaneswar"


@pytest.fixture(scope="module")
def lookup():
    return build_lookup_cache()


@pytest.mark.parametrize(
    "question, college_id",
    [
        ("closing rank for CS at IIIT Bhubaneswar", IIIT_BHUBANESWAR),
        ("what is the cutoff at IIIT Naya Raipur", "international-institute-of-information-technology-naya-raipur"),
        ("closing rank for CS at IIT Bhubaneswar", IIT_BHUBANESWAR),
        ("closing rank for CS at IIIT Lucknow", "indian-institute-of-information-technology-lucknow"),
        ("closing rank for CS at NIT Warangal", "national-institute-of-technology-warangal"),
    ],
    ids=["iiit-bhubaneswar", "iiit-naya-raipur", "iit-bhubaneswar", "indian-iiit-lucknow", "nit-warangal"],
)
def test_short_name_resolves_to_the_college_named(lookup, question, college_id):
    assert _match_college(question, lookup) == college_id


def test_alias_does_not_match_inside_a_longer_word():
    """Word-boundary check on its own, with no database: the only alias is the
    IIT one, so a question that names an IIIT must not resolve to anything.
    """
    lookup = {"alias_to_college_id": {"iit bhubaneswar": IIT_BHUBANESWAR}}

    assert _match_college("closing rank at IIIT Bhubaneswar", lookup) is None
    assert _match_college("closing rank at IIT Bhubaneswar", lookup) == IIT_BHUBANESWAR
