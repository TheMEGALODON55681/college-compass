"""A question that names a college and also asks for alternatives ("colleges
similar to IIT Delhi") must not attach the named college's whole cutoff
history: that prompt came to about 8,477 tokens and a free-tier provider
refused it (a 413 against an 8,000 tokens-per-minute limit). The cap applies
to this mixed case only; a question about one college keeps every row.

Real lookup, reference tables and similarity index; only the encoder is a
stub, since the size under test is the attached history, not the neighbours.
"""

import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from counsellor_fakes import FakeClient
from api.eligibility import load_reference_tables
from models.counsellor import generate_answer
from models.counsellor_retrieval import _historical_closing_ranks, build_context_bundle, build_lookup_cache
from models.similarity import load_similarity_index

MAX_PROMPT_TOKENS = 7000
# 29,058 characters measured for the uncapped "colleges similar to IIT Delhi"
# prompt, against the 8,477 tokens the provider reported for it: 3.43. Rounded
# down so the estimate errs high.
CHARS_PER_TOKEN = 3.4

IIT_DELHI = "indian-institute-of-technology-delhi"


class _FixedEncoder:
    def __init__(self, dim):
        self.dim = dim

    def encode(self, texts, normalize_embeddings=True):
        return np.full((len(texts), self.dim), 1 / np.sqrt(self.dim), dtype="float32")


@pytest.fixture(scope="module")
def state():
    similarity_bundle = load_similarity_index()
    if similarity_bundle is None:
        pytest.skip("no similarity index on disk")
    return {
        "counsellor_lookup": build_lookup_cache(),
        "reference_tables": load_reference_tables(),
        "similarity_bundle": similarity_bundle,
        "embedding_model": _FixedEncoder(similarity_bundle[0].d),
    }


def _bundle_and_prompt(question, state, monkeypatch):
    client = FakeClient(["ok"])
    monkeypatch.setattr("models.counsellor._client", lambda: client)
    bundle = build_context_bundle(question, None, state)
    generate_answer(question, bundle)
    return bundle, "".join(m["content"] for m in client.calls[0])


def _open_rows(records):
    return Counter((r["label"], r["value"]) for r in records if r["field"] == "actual_closing_rank" and r["label"].endswith("category OPEN"))


def test_mixed_question_prompt_stays_under_the_provider_limit(state, monkeypatch):
    bundle, prompt = _bundle_and_prompt("colleges similar to IIT Delhi", state, monkeypatch)

    assert bundle["mode"] == "mixed"
    assert len(prompt) / CHARS_PER_TOKEN < MAX_PROMPT_TOKENS


def test_mixed_question_prompt_stays_under_the_limit_for_every_college(state, monkeypatch):
    colleges = state["counsellor_lookup"]["colleges"]
    largest = 0
    for row in colleges.itertuples(index=False):
        bundle, prompt = _bundle_and_prompt(f"colleges similar to {row.canonical_name}", state, monkeypatch)
        if bundle["mode"] == "mixed":
            largest = max(largest, len(prompt))

    assert 0 < largest / CHARS_PER_TOKEN < MAX_PROMPT_TOKENS


def test_mixed_question_keeps_every_open_row_of_the_named_college(state, monkeypatch):
    bundle, _prompt = _bundle_and_prompt("colleges similar to IIT Delhi", state, monkeypatch)

    full_history = _historical_closing_ranks(IIT_DELHI, None, False)
    assert _open_rows(bundle["records"]) == _open_rows(full_history)


def test_single_college_question_keeps_every_history_row(state, monkeypatch):
    bundle, _prompt = _bundle_and_prompt("closing ranks for IIT Delhi", state, monkeypatch)

    kept = [r for r in bundle["records"] if r["field"] == "actual_closing_rank"]
    assert bundle["mode"] == "structured"
    assert len(kept) == len(_historical_closing_ranks(IIT_DELHI, None, False))
