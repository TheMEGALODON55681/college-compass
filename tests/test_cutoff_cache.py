"""Runnable checks for _get_cutoff_history_cache, the lazy trend history built
on the first /recommend.

It rides on /recommend as an additive feature, so a failed build must degrade
to "no trend" (docs/Rules.md section 8) and must not be cached, or one bad
moment would strip trends until the next restart. It also needs a lock:
without one, concurrent first requests each build the whole cache (measured
on Windows: four at once peaked 48.5 MB above boot instead of 11.5 MB).
"""

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api.main as main_module
from test_memory_fit_regression import _client, _load_fixture


@pytest.fixture
def empty_state(monkeypatch):
    monkeypatch.setattr(main_module, "model_state", {})


def test_failed_build_degrades_and_is_not_cached(monkeypatch, empty_state):
    def broken():
        raise RuntimeError("database went away")

    monkeypatch.setattr(main_module, "build_cutoff_history_cache", broken)
    assert main_module._get_cutoff_history_cache() is None
    assert "cutoff_history_cache" not in main_module.model_state

    monkeypatch.setattr(main_module, "build_cutoff_history_cache", lambda: {("k",): [(2024, 100)]})
    assert main_module._get_cutoff_history_cache() == {("k",): [(2024, 100)]}
    assert "cutoff_history_cache" in main_module.model_state


def test_concurrent_first_requests_build_once(monkeypatch, empty_state):
    builds = []

    def slow_build():
        builds.append(1)
        time.sleep(0.3)
        return {("k",): []}

    monkeypatch.setattr(main_module, "build_cutoff_history_cache", slow_build)
    results = []
    threads = [threading.Thread(target=lambda: results.append(main_module._get_cutoff_history_cache())) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(builds) == 1
    assert len(results) == 4 and all(r is results[0] for r in results)


def test_recommend_survives_a_failed_cache_build(monkeypatch):
    client = _client()
    request = _load_fixture("recommend_1")["request"]

    def broken():
        raise RuntimeError("database went away")

    monkeypatch.delitem(main_module.model_state, "cutoff_history_cache", raising=False)
    monkeypatch.setattr(main_module, "build_cutoff_history_cache", broken)
    resp = client.post("/recommend", json=request)

    assert resp.status_code == 200
    body = resp.json()
    rows = body["safe"] + body["moderate"] + body["dream"]
    assert rows and all(r["trend"] is None for r in rows)
    assert all(r["rounds"] is not None for r in rows)
    assert "cutoff_history_cache" not in main_module.model_state
