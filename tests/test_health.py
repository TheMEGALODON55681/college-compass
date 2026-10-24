"""Runnable checks for /health liveness and the memory readout.

On a cold Render boot the pinger and the platform's own port check both hit
/health while models are still loading. It has to answer at once, say
models_loaded is false, and answer HEAD too, or a keep-warm ping logs an HTTP
error. A load that fails must kill the process (exit status 3, as before),
otherwise the port stays open and a broken deploy goes green.

The real loaders are swapped for one that blocks on an event, so none of this
loads the models.
"""

import sys
import threading
import time
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

import api.main as main_module
from api.main import app

PROC_STATUS = "Name:\tuvicorn\nVmPeak:\t  900000 kB\nVmHWM:\t  200000 kB\nVmRSS:\t  150000 kB\nThreads:\t4\n"


@pytest.fixture
def stalled_boot(monkeypatch):
    """Boot with a loader that blocks until released, then fails. Yields
    (gate, failures): set the gate to let the load fail, failures collects one
    entry per _boot_failed call (the real one would exit the process).
    """
    gate = threading.Event()
    failures = []

    def blocked_loader():
        gate.wait(timeout=10)
        raise RuntimeError("stop here, the test never loads models")

    monkeypatch.setattr(main_module, "model_state", {})
    monkeypatch.setattr(main_module, "load_reference_tables", blocked_loader)
    monkeypatch.setattr(main_module, "_boot_failed", lambda: failures.append(1))
    yield gate, failures
    # The loader thread must reach the patched _boot_failed before monkeypatch
    # restores the real one, which exits the process.
    gate.set()
    deadline = time.time() + 5
    while not failures and time.time() < deadline:
        time.sleep(0.05)
    assert failures, "loader thread never reached the patched _boot_failed"


def test_health_answers_fast_while_models_load(stalled_boot):
    with TestClient(app) as client:
        started = time.perf_counter()
        resp = client.get("/health")
        elapsed = time.perf_counter() - started

        assert resp.status_code == 200
        assert elapsed < 1.0
        body = resp.json()
        assert body["status"] == "not_ready"
        assert body["models_loaded"] is False
        assert {"rss_mb", "rss_peak_mb"} <= set(body)

        assert client.head("/health").status_code == 200
        assert client.get("/meta").status_code == 503
        assert client.get("/similar/any-college").status_code == 503
        assert client.post("/recommend", json={"jee_rank": 12480, "category": "OPEN"}).status_code == 503
        assert client.post("/chat", json={"question": "Which IITs are best for computer science?"}).status_code == 503


def test_ready_is_503_until_models_load_then_200(stalled_boot):
    """Render's health check path. /health stays 200 during the load for the
    pinger; /ready is what keeps the old instance serving until this one can.
    """
    with TestClient(app) as client:
        for method in (client.get, client.head):
            assert method("/ready").status_code == 503
        body = client.get("/ready").json()
        assert body["status"] == "not_ready"
        assert body["models_loaded"] is False

        main_module.model_state.update(ranker=object(), merged_forecasts=object())

        for method in (client.get, client.head):
            assert method("/ready").status_code == 200
        body = client.get("/ready").json()
        assert body["status"] == "ok"
        assert body["models_loaded"] is True
        assert client.get("/health").status_code == 200


def test_ready_waits_for_the_whole_load_including_warmup(monkeypatch):
    """The real _load_models with cheap fakes, blocked inside the ranker
    warm-up (its last step). /ready must stay 503 until the single publish
    that follows, so a deploy never swaps in an instance that cannot serve.
    """
    in_warmup = threading.Event()
    release = threading.Event()

    def blocked_warmup(*args, **kwargs):
        in_warmup.set()
        release.wait(timeout=10)

    monkeypatch.setattr(main_module, "model_state", {})
    monkeypatch.setattr(main_module, "load_reference_tables", lambda: (pd.DataFrame({"state": ["Delhi"]}), None, None))
    monkeypatch.setattr(main_module, "build_forecasts", lambda: None)
    monkeypatch.setattr(main_module, "merge_forecasts_with_colleges", lambda forecasts, colleges: "merged")
    monkeypatch.setattr(main_module, "load_ranker", lambda: "ranker")
    monkeypatch.setattr(main_module, "load_probability_artifacts", lambda: "probability")
    monkeypatch.setattr(main_module, "load_similarity_index", lambda: None)
    monkeypatch.setattr(main_module, "build_lookup_cache", lambda: {})
    monkeypatch.setattr(main_module, "score_candidates_for_student", blocked_warmup)

    with TestClient(app) as client:
        assert in_warmup.wait(timeout=10), "loader never reached the warm-up"
        assert client.get("/ready").status_code == 503
        assert client.get("/health").json()["models_loaded"] is False

        release.set()
        deadline = time.time() + 10
        while client.get("/ready").status_code != 200:
            assert time.time() < deadline, "/ready never turned 200 after the load finished"
            time.sleep(0.05)


def test_failed_load_exits_instead_of_serving_forever(stalled_boot):
    gate, failures = stalled_boot
    with TestClient(app):
        gate.set()
        deadline = time.time() + 5
        while not failures and time.time() < deadline:
            time.sleep(0.05)
    assert failures == [1]


def test_boot_failure_handler_exits_with_status_3(monkeypatch, capsys):
    exits = []
    monkeypatch.setattr(main_module.os, "_exit", exits.append)
    try:
        raise RuntimeError("no such table: colleges")
    except RuntimeError:
        main_module._boot_failed()

    assert exits == [3]
    assert "no such table: colleges" in capsys.readouterr().err


def test_memory_readout_parses_proc_status(tmp_path):
    status = tmp_path / "status"
    status.write_text(PROC_STATUS)
    assert main_module._memory_readout(status) == {"rss_mb": 146.5, "rss_peak_mb": 195.3}


def test_memory_readout_is_null_without_proc(tmp_path):
    assert main_module._memory_readout(tmp_path / "no-such-file") == {"rss_mb": None, "rss_peak_mb": None}
