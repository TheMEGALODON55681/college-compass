# College Compass

A JEE Main / JoSAA college recommendation system. Given a student's rank and
category, it returns eligible college-branches banded safe/moderate/dream,
predicted with a trained cutoff regressor and calibrated admission
probabilities. It also provides item-to-item "similar colleges" retrieval, a
grounded counsellor chatbot, and a downloadable PDF counselling report.

See [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for a gap to check before using the
counsellor with real students.

## Stack

- Backend: FastAPI + SQLAlchemy, SQLite for local dev (`DATABASE_URL` swaps to Postgres)
- Models: LightGBM (cutoff regressor, ranker), isotonic calibration (admission probability), sentence-transformers + FAISS (similarity retrieval)
- PDF: reportlab
- Frontend: React + TypeScript + Vite

## Setup

```
pip install -r requirements.txt
cp .env.example .env
```

The SQLite database (`college_compass.db`) ships with the repo. `DATABASE_URL`
defaults to it; only set it if you're pointing at Postgres instead. All
database access routes through `db/connection.py` - see "Postgres migration"
below.

## Running

Backend:

```
python -m uvicorn api.main:app --port 8000
```

Frontend:

```
cd frontend
npm install
npm run dev
```

Startup loads the trained ranker, regressor forecasts, calibrated
admission-probability artifacts, the similarity FAISS index, and a
sentence-transformer for the counsellor's semantic retrieval - all once, not
per request. Endpoints will 503 until this finishes.

## Rebuilding trained artifacts

These are checked into `models/artifacts/` already; only rerun if the
underlying data changes:

```
python -m models.cutoff_regressor        # trains the closing-rank regressor
python -m models.admission_probability   # calibrates admission probability
python -m models.ranker                  # trains the personalization ranker
python -m models.similarity              # builds the college-similarity FAISS index
```

## Postgres migration

Every module reads its database through `db/connection.py` - one
`get_database_url()`/`get_engine()` pair, keyed on the single `DATABASE_URL`
env var. Unset, or pointing at the shipped SQLite file, runs on SQLite;
`postgresql://...` runs on Postgres. Nothing else in the app knows or cares
which backend is active. This is a substrate swap only - no model, endpoint,
or output changes with the backend.

To move to Postgres:

1. Create an empty Postgres database.
2. Run the migration, pointing `DATABASE_URL` at it (or pass `--target`):
   ```
   DATABASE_URL=postgresql://user:pass@host:5432/college_compass python -m db.migrate_to_postgres
   ```
   This creates the schema (same tables/columns/keys as SQLite, via the same
   `db/models.py` definitions - see `db/schema.sql`), loads every row from
   the shipped SQLite file, and reports per-table row counts before and
   after. It's idempotent: rerunning it clears each target table and reloads
   it fresh from SQLite rather than duplicating rows.
3. Run the parity check before trusting the new backend for anything real:
   ```
   python -m db.parity_check --postgres-url postgresql://user:pass@host:5432/college_compass
   ```
   This runs the same representative student profiles, counsellor questions,
   and similarity profile-building through the real application code against
   both SQLite and the new Postgres database. It asserts every output is
   identical - row counts, predicted closing ranks, bands, calibrated
   admission probabilities, and counsellor context records - and exits
   non-zero on any mismatch. Verified in this environment (no system
   Postgres or Docker available) using a temporary local Postgres instance
   for the check - re-run it against your actual target Postgres before
   relying on the migration there; a different Postgres version or locale is
   exactly the kind of thing this check exists to catch.
4. Once parity passes, set `DATABASE_URL` to the Postgres URL for the running
   app (`api.main`'s startup log prints which backend is active, and
   `GET /meta` reports `database_backend: "sqlite" | "postgres"`, never the
   connection string).

To roll back, unset `DATABASE_URL` (or point it back at the SQLite file) and
restart - SQLite keeps working from the same code, untouched by any of the
above.

## API

- `GET /health` - readiness check
- `GET /meta` - known categories/states, the active database backend (`"sqlite"` or `"postgres"`, never the connection string), plus whether the counsellor and an LLM endpoint are configured (presence only, never the value)
- `POST /recommend` - student profile in, banded eligible college-branches out
- `GET /similar/{college_id}` - top-5 colleges similar by type, location, ranking, and programs offered (item-to-item, not personalized)
- `POST /chat` - grounded counsellor: a question (plus optional student profile) in, an answer grounded in the system's own data out, with its source college_ids
- `POST /report` - same student profile as `/recommend`, returns a downloadable PDF counselling report built from that exact recommendation output

## The grounded counsellor (`/chat`)

The counsellor only states a rank, cutoff, probability, or fee that appears
verbatim in the context it retrieved for the question - never a fabricated
number. This is enforced in code, not just prompted:

- `models/counsellor_retrieval.py` builds a context bundle from the system's
  own data. If the question names a college (by full name or a common alias
  like "IIT Bombay" or "MNIT Jaipur"), it reuses the existing eligibility
  filter, cutoff regressor forecast, and calibrated admission probability -
  the same numbers `/recommend` serves. If it doesn't, it falls back to
  semantic retrieval over the existing similarity FAISS index (the question
  is embedded at request time; no second index is built). Placement/package
  questions are declined without ever reaching the LLM.
- `models/counsellor.py` calls a provider-agnostic OpenAI-compatible chat
  endpoint (`LLM_ENDPOINT`, `LLM_MODEL`, `LLM_API_KEY` env vars - no vendor
  hardcoded, defaults to a local Ollama-style endpoint), then re-extracts
  every number in the model's answer and checks it against the bundle's real
  values with an exact match. An ungrounded number gets one regeneration
  attempt with a stricter instruction; if it's still there, it's stripped
  from the answer rather than shown, and `blocked_ungrounded_figure` is set
  on the response.
- If the LLM endpoint isn't reachable, `/chat` returns a clean, honest error
  - never a fabricated answer.

Run `python -m pytest tests/test_counsellor_grounding.py` to see the
validator catch and block a fabricated rank, including one test against a
real unreachable endpoint (no mocking).

To get generated answers instead of the clean unreachable-endpoint message,
point `LLM_ENDPOINT`/`LLM_MODEL` at a running OpenAI-compatible server
(Ollama, LM Studio, vLLM, or a hosted provider).

## The PDF counselling report (`/report`)

`api/report_data.py` reshapes the exact dict `/recommend` already returns
(via a shared `compute_recommendation` function) into a report model - it
does not recompute eligibility, cutoffs, bands, or probabilities.
`api/report_pdf.py` renders that model with reportlab. The report includes a
student-profile header, one table per non-empty band (safe/moderate/dream)
with predicted closing rank and admission chance, a "next steps" page of
real JoSAA process facts (multiple rounds, freeze/float/slide, cutoffs vary
year to year), and a scope footer. Cold-start admission-probability figures
are marked "(approx.)" in the PDF table, matching the UI's
approximate-estimate label. No placement or package data appears anywhere in
the report. PDF metadata (title/author/creator/producer) is set to "College
Compass" only - no library or vendor name.
