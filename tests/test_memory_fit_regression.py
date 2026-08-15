"""Phase 0 regression gate for the memory-fit backend work: replays every
golden request captured in tests/fixtures/baseline/ and asserts equality.
Must pass before and after every phase of that work - if it fails, stop and
report, do not adjust the fixtures to make it pass.

/recommend, /similar, /meta, /cutoffs: exact equality on the full response,
ordering included.

/chat: never calls the live LLM - its prose is expected to vary between runs
(see models/counsellor.py's own grounding validator, which exists precisely
because the model's wording isn't trustworthy). generate_answer is swapped
for a deterministic fake so the real route still runs end to end (request
validation, home-state check, building the context bundle, mapping the
response), and the assertions cover what must never drift across a
memory-fit refactor: source_college_ids from the real route, plus the
routing mode and the full set of grounded values the validator would check
any answer against, read from build_context_bundle directly since /chat's
response schema doesn't expose either.

Note: /meta's fixture bakes in this machine's current .env (llm_endpoint_
configured, database_backend) - exact-equality here is only meant to hold
across phases of this refactor in this same environment, not across a fresh
clone with a different .env.
"""

import atexit
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

import api.main as main_module
from api.main import app
from models.counsellor import _grounded_value_strings
from models.counsellor_retrieval import build_context_bundle

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "baseline"

_holder = {}


def _client():
    """Opened once and reused across every test in this module - the app's
    lifespan loads the ranker, forecasts, similarity index, and embedding
    model, which is expensive enough that per-test setup would make this
    suite impractical to run before and after every phase, as required.
    """
    if "client" not in _holder:
        context_manager = TestClient(app)
        _holder["client"] = context_manager.__enter__()
        atexit.register(context_manager.__exit__, None, None, None)
    return _holder["client"]


def _load_fixture(name):
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _fixture_names(prefix):
    return sorted(p.stem for p in FIXTURES_DIR.glob(f"{prefix}*.json"))


def test_recommend_matches_baseline():
    for name in _fixture_names("recommend_"):
        fixture = _load_fixture(name)
        resp = _client().post("/recommend", json=fixture["request"])
        assert resp.status_code == 200
        assert resp.json() == fixture["response"], name


def test_similar_matches_baseline():
    for name in _fixture_names("similar_"):
        fixture = _load_fixture(name)
        resp = _client().get(f"/similar/{fixture['request']['college_id']}")
        assert resp.status_code == 200
        assert resp.json() == fixture["response"], name


def test_meta_matches_baseline():
    fixture = _load_fixture("meta")
    resp = _client().get("/meta", params=fixture["request"])
    assert resp.status_code == 200
    assert resp.json() == fixture["response"]


def test_cutoffs_matches_baseline():
    for name in _fixture_names("cutoffs_"):
        fixture = _load_fixture(name)
        resp = _client().get("/cutoffs", params=fixture["request"])
        assert resp.status_code == 200
        assert resp.json() == fixture["response"], name


def _fake_generate_answer(question, bundle):
    return {
        "answer": "[test fake - live LLM not called]",
        "source_college_ids": bundle["college_ids"],
        "blocked_ungrounded_figure": False,
        "error": None,
    }


def test_chat_routing_matches_baseline():
    """Covers all five captured paths: named-college structured lookup,
    fuzzy semantic, mixed (named college + wants alternatives), the
    placement refusal, and a question crafted to stress the grounding
    validator's strip-and-retry path.
    """
    client = _client()
    original_generate_answer = main_module.generate_answer
    main_module.generate_answer = _fake_generate_answer
    try:
        for name in _fixture_names("chat_"):
            fixture = _load_fixture(name)
            request = fixture["request"]

            resp = client.post("/chat", json=request)
            assert resp.status_code == 200
            assert resp.json()["source_college_ids"] == fixture["response"]["source_college_ids"], name

            bundle = build_context_bundle(request["question"], request.get("student_profile"), main_module.model_state)
            assert bundle["mode"] == fixture["routing_mode"], name
            assert sorted(_grounded_value_strings(bundle)) == fixture["grounded_values"], name
    finally:
        main_module.generate_answer = original_generate_answer


if __name__ == "__main__":
    test_recommend_matches_baseline()
    test_similar_matches_baseline()
    test_meta_matches_baseline()
    test_cutoffs_matches_baseline()
    test_chat_routing_matches_baseline()
    print("ok")
