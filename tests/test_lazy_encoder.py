"""Phase 2 memory-fit gate: the ONNX encoder (models/onnx_encoder.py,
~90MB of weights, plus the onnxruntime/tokenizers import cost) must load on
first semantic-retrieval use only, never at API startup. /recommend,
/similar, /report, /meta, /cutoffs, and /health are the non-semantic
surface - none of them may trigger the load.

Needs its own fresh TestClient (own lifespan run), not the shared one in
test_memory_fit_regression.py - that module's client is reused across tests
in the same process, and some of those tests do exercise the semantic /chat
path, which would load the encoder and make this assertion meaningless.
"""

import atexit
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

import api.main as main_module
from api.main import app
from test_memory_fit_regression import _wait_until_loaded

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "baseline"

_holder = {}


def _client():
    if "client" not in _holder:
        context_manager = TestClient(app)
        _holder["client"] = context_manager.__enter__()
        atexit.register(context_manager.__exit__, None, None, None)
        _wait_until_loaded(_holder["client"])
    return _holder["client"]


def _load_fixture(name):
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def test_non_semantic_routes_never_load_encoder():
    client = _client()
    assert "embedding_model" not in main_module.model_state

    recommend_fixture = _load_fixture("recommend_1")
    resp = client.get("/health")
    assert resp.status_code == 200 and resp.json()["status"] == "ok"
    assert "embedding_model" not in main_module.model_state

    resp = client.get("/meta")
    assert resp.status_code == 200
    assert "embedding_model" not in main_module.model_state

    resp = client.post("/recommend", json=recommend_fixture["request"])
    assert resp.status_code == 200
    assert "embedding_model" not in main_module.model_state

    resp = client.post("/report", json=recommend_fixture["request"])
    assert resp.status_code == 200
    assert "embedding_model" not in main_module.model_state

    similar_fixture = _load_fixture("similar_indian-institute-of-technology-bombay")
    resp = client.get(f"/similar/{similar_fixture['request']['college_id']}")
    assert resp.status_code == 200
    assert "embedding_model" not in main_module.model_state

    cutoffs_fixture = _load_fixture("cutoffs_1")
    resp = client.get("/cutoffs", params=cutoffs_fixture["request"])
    assert resp.status_code == 200
    assert "embedding_model" not in main_module.model_state


def test_semantic_chat_does_load_encoder():
    """The flip side: the one path that's supposed to load it, does."""
    client = _client()
    chat_fixture = _load_fixture("chat_semantic_fuzzy")
    resp = client.post("/chat", json=chat_fixture["request"])
    assert resp.status_code == 200
    assert "embedding_model" in main_module.model_state


if __name__ == "__main__":
    test_non_semantic_routes_never_load_encoder()
    test_semantic_chat_does_load_encoder()
    print("ok")
