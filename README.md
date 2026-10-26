# College Compass

A JEE Main / JoSAA college recommendation system. Give it your rank and
category, get back eligible college-branches banded safe, moderate, and
dream, each with a predicted closing rank and a calibrated admission
probability. It also provides item-to-item "similar colleges" retrieval, a
grounded counsellor chatbot, and a downloadable PDF counselling report.

Live at [college-compass-sandy.vercel.app](https://college-compass-sandy.vercel.app).
The backend, including a browsable API at `/docs`, is at
[college-compass-il7k.onrender.com](https://college-compass-il7k.onrender.com).

This is a decision aid, not an official JoSAA tool and not advice. See
[Scope and limitations](#scope-and-limitations) before you rely on it.

## The honesty premise

Every number on screen is one of three things: real historical JoSAA data,
a model output with an honest error story attached, or the student's own
input echoed back. Nothing is invented, which is what separates this from
the "predictor" sites that guess last year's cutoffs at you with false
confidence.

Two guarantees back that up, both enforced in code, not just written in a
prompt:

- Cold-start estimates are visibly different from confident ones. A college
  with too little year-over-year history gets a hatched confidence bar and
  an "approximate" label, in the UI and in the PDF. Never a clean bar for a
  wobbly number.
- The counsellor chatbot re-extracts every number it states and checks it
  against real retrieved data with an exact match. A number that doesn't
  match gets one stricter retry, then gets stripped from the answer rather
  than shown.

## Screenshots

Captured against the live app and a real backend, rank `12480`, category
`General`, home state `Delhi`. That's the same example profile the landing
page's own sample shortlist uses, and it returns a real mix of results: 586
likely, 54 fair chance, 32 reach.

| | |
|---|---|
| ![Landing page hero](docs/screenshots/landing.png) | ![Rank card input form](docs/screenshots/rank-card.png) |
| The landing page hero, with the sample admit card fully assembled and its probability meters filled in | The rank card filled in with the example profile, before submit |
| ![Banded results with probability meters](docs/screenshots/results.png) | ![College detail with cutoff trend](docs/screenshots/college-detail.png) |
| Likely, fair chance, and reach results for that profile, each with a real admission probability | The admission probability header and the nine-year cutoff trend for a likely match |
| ![Counsellor answering with sources](docs/screenshots/counsellor.png) | ![The report screen and its download button](docs/screenshots/report.png) |
| The counsellor answering a real cutoff question, sourced to the exact college it cites | The report screen, with the shortlist summary and a completed PDF download |

## Architecture, mapped

The request path end to end, from the student's form to every feature it
powers:

```mermaid
flowchart TD
    A[Rank card form: rank + category] --> B[POST /recommend]
    B --> C[Eligibility filter over regressor forecast]
    C --> D[Ranker reorder]
    D --> E[Banded results: safe / moderate / dream]
    E --> F[GET /similar]
    E --> G[POST /report PDF]
    E --> H[POST /chat grounded counsellor]
```

The PDF report and the grounded counsellor both reuse this exact
recommendation output. Neither recomputes anything. See "How it works"
below for what happens at each step.

A separate auto-generated dependency graph covers module-level coupling
instead of request flow: 500 nodes and 983 edges across 27 communities,
pulled straight from the source with AST parsing plus semantic extraction,
zero import cycles. Use it to audit coupling, not to follow the request
flow above. It predates the current frontend, so its backend and data
pipeline nodes hold up but its frontend-side nodes describe the previous
UI, due for a refresh. The SVG is at
[docs/architecture-graph.svg](docs/architecture-graph.svg), an interactive
version at [docs/architecture-graph.html](docs/architecture-graph.html),
and the full audit is in
[docs/ARCHITECTURE_GRAPH_REPORT.md](docs/ARCHITECTURE_GRAPH_REPORT.md).

## Build the database

A fresh clone has no `college_compass.db`: it is gitignored, along with the
`data/raw/` and `data/processed/` directories the pipeline builds it from.
Every trained model artifact (regressor, ranker, calibrator, FAISS index)
still ships with the repo and needs none of this. Do one of the two paths
below, once, from the repo root, before [Quickstart](#quickstart).

**Download the published copy (about a minute).** The built database is a
gzip asset on a GitHub release. `scripts/fetch_db.py` downloads it,
decompresses it, and checks the result against a SHA-256 pinned in the
script:

```
pip install -r requirements.txt
python scripts/fetch_db.py
```

A failed download or a checksum mismatch raises and leaves no database
behind. If `college_compass.db` already exists and matches, the script does
nothing. If it exists and differs, for example a copy you rebuilt, the script
refuses to overwrite it. Render's build runs this same script (see
[The live deployment](#the-live-deployment)).

**Or rebuild it from the public sources (a few minutes).**

```
pip install -r requirements.txt
python -m data_pipeline.ingest
python -m data_pipeline.normalize
python -m data_pipeline.build_dataset
```

- `data_pipeline.ingest` downloads every raw source (JoSAA's round-wise
  2016-2020 cutoffs, the 2024 and 2025 snapshots, two independent 2021-2023
  backfills, NIRF's engineering rankings) into `data/raw/`. Every source is
  a public file on GitHub or nirfindia.org, no login or API key. It is
  idempotent, so re-running it after a failed or partial pull only fetches
  what is still missing.
- `data_pipeline.normalize` reconciles those raw sources into
  `data/processed/`, as five Parquet files (colleges, programs, cutoffs,
  seat_counts, nirf_rankings), via `pyarrow`.
- `data_pipeline.build_dataset` loads those Parquet files into
  `college_compass.db` (or `DATABASE_URL`, if set) and prints a coverage
  report naming exactly which year and institute-type combinations have
  real data.

Each step logs its own progress as it runs.

**Publishing a new database.** After a rebuild, compress it, hash the
uncompressed file, and attach the `.gz` to a new GitHub release:

```
python -m gzip college_compass.db
python -c "import hashlib; print(hashlib.sha256(open('college_compass.db', 'rb').read()).hexdigest())"
```

Then set `DB_URL` and `DB_SHA256` at the top of `scripts/fetch_db.py`. The
checksum covers the decompressed file, so any gzip level produces a valid
asset.

## Quickstart

Backend:

```
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn api.main:app --port 8000
```

Every trained model artifact (regressor, ranker, calibrator, FAISS index)
ships with the repo; the database does not (see
[Build the database](#build-the-database)). Startup loads everything once;
the API 503s until that finishes, then stays fast. One exception: the
counsellor's text encoder loads on the first semantic question instead of
at startup, so that first question is slower than the ones after it.

Frontend, in a second terminal:

```
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open the printed local URL (`http://localhost:5173` by default). The
frontend pulls its own category and state options from the backend, so the
two can never drift out of sync.

`VITE_API_BASE` (in `frontend/.env`) is the backend's origin. Leave it blank
for local dev: every API call goes through the Vite dev server's own proxy
(`frontend/vite.config.ts`), which forwards the backend's root-mounted paths
(`/recommend`, `/chat`, `/report`, `/meta`, `/similar`, `/cutoffs`,
`/health`) to `http://localhost:8000`, so the browser never hits a CORS
wall. Set `VITE_API_BASE` to the real backend's origin only when the
frontend is built and served from somewhere the proxy can't reach, for
example a separately hosted static build.

For production, the simplest path is one process: run
`npm run build` inside `frontend/`, and the backend serves the result
directly, static assets and all, the moment `frontend/dist` exists. No
second server or reverse proxy needed. Hosting the frontend separately
works too. Either way, `CORS_ORIGINS` and `VITE_API_BASE` are the only two
settings that change.

### The live deployment

The live instance is the split-hosting case above: a static Vercel build
for the frontend, a separate Render service for the backend. The
frontend's `VITE_API_BASE` points at the Render backend's origin, and the
backend's `CORS_ORIGINS` allows the Vercel origin. That's the whole
connection between them.

Render's build command installs the dependencies, then fetches the database
(the file is not in git):

```
pip install -r requirements.txt && python scripts/fetch_db.py
```

The service opens its port first and loads the models in a background
thread. `GET` and `HEAD /health` answer while that runs and report
`models_loaded: false` until it finishes; every endpoint that needs a model
returns 503 until then. If the load fails, the process exits with status 3,
so a broken deploy fails instead of going live without models. On Linux,
`/health` also reports `rss_mb` and `rss_peak_mb` (current and peak resident
memory), because Render's free plan has no memory graph. Both are `null`
elsewhere.

Set the service's Health Check Path to `/ready` (Settings, Health Check
Path). `/ready` returns 503 until every model is loaded and 200 after. With
it set, Render keeps the old instance serving until the new one answers 200,
so a boot that runs out of memory fails the deploy and the live site stays up.
`/health` stays 200 during the load, for the keep-warm job.

The boot reads only the cutoff rows and columns the forecast uses, in chunks,
and hands the freed Arrow buffers back to the system. On a Windows
measurement that cut the boot peak from about 640 MB to about 320 MB. The live
numbers on Render (2026-10-26) are `rss_mb` 318 to 328 MB after boot and
`rss_peak_mb` 353 to 368 MB, against the 512 MB limit.

A cron-job.org job keeps the free instance awake: `GET /health` every 10
minutes with a 30 second timeout, failure notification on. Use the https
address, because http returns a 301 that cron-job.org counts as a failure. A
sleeping Render instance answers with its own 503 "waking up" page, and a
short ping can fail to start it. If the job is ever paused, open the
site once in a browser and wait for it to load before you turn the job back on.

## How it works

**Data pipeline.** A normalization step reconciles six public sources
(JoSAA round-level cutoffs, NIRF rankings, a hand-maintained fees and
hostel reference table) into one schema and loads it into SQLite. Postgres
is a one-env-var swap away for anyone who wants it; the substrate never
changes what the app computes.

**Cutoff regressor.** A LightGBM model predicts the year-over-year *change*
in a college-branch's closing rank, not the raw rank itself. Trees can't
extrapolate past what they were trained on, so predicting a delta and
adding it to last year's real number keeps every forecast inside the
model's trained range. A separate cold-start fallback model covers
college-branches with too little history for the main one.

**Eligibility and banding.** Given a rank and category, the system resolves
quota against home state and bands every reachable college-branch safe,
moderate, or dream based on how much margin the forecast gives you. This
step decides what you're eligible for; nothing downstream is allowed to
change that.

**Personalization ranker.** An LGBMRanker reorders eligible results by fit
(state, budget, branch taste, NIRF appetite) without ever touching
eligibility. Its relevance label is built from real revealed preference,
and closing-rank-derived signals are deliberately excluded from its
features, so it can't just learn to reconstruct the label from itself.

**Admission probability.** Isotonic calibration, fit on a held-out
validation year, corrects a residual-based raw probability. The result is
rounded to the nearest 5% before it's ever shown, so it never implies more
precision than the model actually has.

**Cutoff trend.** Every result row and the college detail screen carry a
deterministic Tightening, Stable, or Loosening label, built from an
ordinary least squares slope over that college-branch-category-quota's
settled year-over-year closing rank. Below three usable years the label
reads `Insufficient history` instead of guessing. The slope is detrended
first: JoSAA's seat pool expanded broadly from 2016 to 2024, so a raw slope
mostly measures that system-wide drift rather than anything specific to one
college, and a raw threshold once labeled 57% of colleges Loosening, which
told a student nothing. The classifier subtracts the median normalized
slope across the same population (0.0412, fit on 2016-2024 data) before
comparing the result against a neutral band of 0.03. Refit against that
residual distribution, the actual split across colleges with enough history
is 36.6% Stable, 32.7% Tightening, 30.7% Loosening. The whole settled
history table (about 50,600 year-rank pairs) is built once per process and
cached in memory, not re-queried per request, since it only changes when
the database is reingested.

**Round projection.** A naive per-round closing-rank curve, computed on
demand for each `/recommend` row and anchored so the last round always
equals the existing final-round forecast exactly. JoSAA's round count
varies by year (6 rounds in 2016 and 2020-2022, 7 in 2017-2019), so the
ratio between a round's closing rank and the final round's is keyed on
fractional position in the sequence rather than absolute round number, and
computed per category and branch family (CS-adjacent or core) from
2016-2022 data only, since 2023 and 2024 carry no round breakdown. Checked
against two held-out years, trained on the other six each time: a 6-round
season (2021) and a 7-round season (2018), so the win isn't just an
artifact of testing on the round count 2026 happens to share. Both beat
the trivial "every round equals the final round" baseline at every round
position - 2021 by 27-49% depending on position, 37% overall; 2018 by
17-42%, 30% overall. The 7-round year's smaller margin is expected, not a
weakness: its keying folds two of that year's rounds into one bucket, so
part of what the ratio is being scored against is its own compression.
Either way the ratio wins clearly, and 2021 and 2022, the two most recent
years with round data, agree on 6 rounds, which is what 2026 is projected
to be. There is no learned round model: a model trained on 2016-2022 would
have no later year with round data left to validate against, so this
pattern is what ships, not a trained one. Nothing about it is stored; it's
arithmetic on a forecast the system already computed. The ratio table
(`models/round_forecast_ratios.py`) is generated, not hand-maintained -
`python -m models.build_round_ratio_table` refits it from the database and
re-runs both held-out checks, so a future reingest can't leave it silently
stale.

**Grounded counsellor.** The system routes a question to structured lookup
(a named college, reusing the exact forecast and probability numbers
`/recommend` already computed) or semantic retrieval (FAISS similarity, for
fuzzier questions), building a context bundle where every fact carries its
own source. The language model answers from that bundle, and a code-level
validator checks every number in the answer against it before the answer
is ever returned.

## Scope and limitations

Stated plainly, because a hidden limitation is worse than a stated one.

- **No placement, package, salary, or CTC data, anywhere, ever.** The
  counsellor declines those questions before they reach the language
  model. This is a deliberate exclusion, not a gap.
- **Gender-Neutral seats only.** Female-only supernumerary seats are a
  real, separate, smaller pool this system doesn't cover.
- **Forecasts are genuine forecasts.** Any year without a real closing-rank
  label is evaluated on held-out past years, never on data that doesn't
  exist yet.
- **A decision aid, not an official source.** Fees are coarse
  per-institute-type approximations. Check the institute's current fee
  circular before making a real decision.
- **Category rank, not CRL, for reserved categories.** OPEN uses overall
  rank; EWS/OBC-NCL/SC/ST use category rank, matching how JoSAA actually
  publishes its own cutoffs.
- **Grounding checks value membership, not attribution.** The validator
  confirms a stated number appears somewhere in the real retrieved data,
  but doesn't yet confirm it's the right *kind* of number for the right
  college. In a multi-college answer, a genuinely real figure could in
  principle get attached to the wrong college. Documented in
  [KNOWN_ISSUES.md](KNOWN_ISSUES.md), not yet hardened.
- **A counsellor question about one college, with no rank given, can still
  hit a free-tier provider's rate limit.** It attaches every cutoff row for
  that college, which can exceed the provider's per-minute token cap. The
  counsellor then says the provider refused the request and suggests a
  narrower question, instead of reporting the model as down. Questions that
  also ask for alternatives stay under the cap.
- **Closing ranks quoted without a rank can mix seat pools.** With no rank
  and category, the counsellor falls back to a college's latest actual
  closing ranks, and those include Female-only seats without saying which
  pool a rank belongs to. With a rank and category the answer comes from the
  Gender-Neutral forecast. Documented in [KNOWN_ISSUES.md](KNOWN_ISSUES.md),
  not yet fixed.
- **The backend runs on a free instance: 512MB RAM, a fraction of a CPU.**
  Requests are slower than the screenshots suggest.
- **The first counsellor question that doesn't name a specific college is
  the slow one.** It loads the sentence encoder on demand, the same
  tradeoff described in [Quickstart](#quickstart).
- **A cold backend takes time to wake up.** A keep-warm ping hits `/health`
  every ten minutes, so this should be rare. After an idle spell or a
  redeploy, the first request can still land while the models load. It gets
  a 503 ("models are still loading, try again shortly") and the student
  retries by hand. A proper waking-up screen is planned.

Full detail on all of the above, plus what's already been tested and what
hasn't, is in [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## Tech stack

Backend: FastAPI, SQLAlchemy (SQLite locally, Postgres via one env var).
Machine learning: LightGBM, isotonic calibration, an ONNX Runtime encoder
(all-MiniLM-L6-v2) with a FAISS index. PDF: reportlab. Frontend: React 18,
TypeScript, Vite, react-router for routing, motion for animation, recharts
for the cutoff chart, lucide-react for icons, and a hand-authored
CSS-variable design system with no component framework. Deployed on
Vercel (frontend) and Render (backend).
