# Build log

## 2026-08-15 - Memory-fit: Phase 0, baseline capture

Captured RSS at three checkpoints (startup, first `/recommend`, first
semantic `/chat`) and golden-output fixtures for `/recommend`, `/similar`,
`/chat`, `/meta`, `/cutoffs` under `tests/fixtures/baseline/`.
`tests/test_memory_fit_regression.py` replays them and must pass before and
after every phase of this work. Baseline: 683.7MB RSS after startup, 58.8s
boot.

## 2026-08-15 - Memory-fit: Phase 1, PyTorch to ONNX Runtime

Replaced `sentence-transformers` (PyTorch) with an ONNX Runtime export of
the same `all-MiniLM-L6-v2` weights (`models/onnx_encoder.py`), reproducing
sentence-transformers' tokenize / mean-pool / L2-normalize pipeline
exactly. Verified against the old encoder on 55 queries: worst-case cosine
similarity 0.99999988, identical FAISS top-10 neighbour lists. `torch` and
`sentence-transformers` fully uninstalled. `models/similarity.py`'s offline
`build_index()` and `db/parity_check.py` switched to the ONNX encoder too,
so the index-rebuild workflow and the migration-parity check keep
exercising the real path. RSS after startup: 384.6MB, boot 25.2s.

## 2026-08-15 - Memory-fit: Phase 2, lazy-load the encoder

Moved `OnnxSentenceEncoder` construction out of `api/main.py`'s startup
into a lazy, cached getter in `models/counsellor_retrieval.py`, loaded only
on the first semantic `/chat` question. `/recommend`, `/similar`,
`/report`, `/meta`, `/cutoffs`, `/health` never trigger it - covered by
`tests/test_lazy_encoder.py`'s fresh-process check. Zero network calls
proven directly (a socket-level block around encoder construction and
encode) and by an `HF_HUB_OFFLINE=1` boot producing identical timing and
memory to a normal boot.

Boot time 23.37s to 17.12s; RSS after startup 385.5MB to 255.4MB. Peak RSS,
after the first semantic chat triggers the load, is 391.3MB - close to the
old 400.1MB, since the memory cost moved rather than disappeared. That
first semantic question now costs about 5.7s more; every question after it
costs nothing extra.

## 2026-08-15 - Memory-fit: Phase 3, skipped

Phase 3 (materialize the forecast table into SQLite) was conditional on
RSS staying above 300MB after Phase 2. It did not - peak RSS is 391.3MB
against a 512MB cap. The remaining open question is Windows-measured RSS
versus the actual Linux cgroup on Render; more local measurement work
cannot resolve that gap, only a real deploy can, so Phase 3 was skipped
rather than chased further on a Windows dev machine.

## 2026-08-15 - Memory-fit: Phase 4, docs and final verification

Updated README's tech stack line and added the first-semantic-question
latency note to the Quickstart section. Added the strip-and-retry
substring-corruption bug (found in the Phase 0 baseline fixtures) to
KNOWN_ISSUES.md, documented and not fixed. Confirmed `requirements.txt`
already exact-pins `numpy==2.5.1` and `joblib==1.5.3` to the versions this
work was verified against - the joblib `DeprecationWarning` about NumPy
2.5 array-shape assignment at `.joblib` load time is a known joblib/numpy
interaction, not a version drift risk, since the pin prevents a different
resolve. Full suite 16/16, frontend build unaffected.
