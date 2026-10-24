# Known issues

## A deploy goes live, then runs out of memory at boot

On 2026-10-23 Render built commit 5741275, fetched the database from the
`db-v1` release and reported the service live at 22:34 IST. Within a minute it
logged "Ran out of memory (used over 512MB) while running your code", again at
22:35, and then restarted about every 90 seconds. `/health` returned an error
page. The developer rolled production back to d051b37.

The background load moved the memory peak to after the platform's port check.
Render marks a deploy live once the port is bound and `/health` answers 200,
retires the old instance, and only then does the load reach its peak. Before
the background load, an out-of-memory kill during boot failed the deploy and
the old instance kept serving. Every run in Render's log died before it printed
"loading trained ranker...", so the peak sat in the first load step.

Profiling on Windows found it in `build_forecasts`. `SELECT * FROM cutoffs`
read all 352,432 rows and 11 columns at once, then the code kept a filtered
copy (185,945 Gender-Neutral rows from 2018 on) and made another while
collapsing to one row per group and year. That one step raised the peak working
set from 216 MB to 637 MB. Nothing after it moved the peak.

Fix, in code and not yet deployed:

- `/ready` returns 503 until every model is published and 200 after. With
  Render's Health Check Path set to `/ready`, a boot that runs out of memory
  fails the deploy and the old instance keeps serving. `/health` is unchanged.
- `load_serving_cutoffs()` (`models/regressor_dataset.py`) filters in SQL, reads
  the 7 columns the features use, and streams the rows in 20,000-row chunks.
  `build_forecasts` output is identical to the old read: same rows, same order,
  same dtypes.
- The boot calls pyarrow's `release_unused()` after the forecast merge. Without
  it Arrow's allocator kept about 50 MB of freed read buffers for the life of
  the process.

Measured on Windows with Render's thread settings, real uvicorn: boot peak
working set 639 to 640 MB before, 320 to 324 MB after. Settled after boot 254 to
259 MB (258 to 264 MB before). After one `/recommend` and one semantic `/chat`
384 to 389 MB, lifetime peak 409 to 412 MB. Not measured on Linux under a
512 MB cap: Docker is not installed on the development laptop, and the
developer chose Windows-only measurement. Windows working set is a regression
signal, not Render's number.

This entry closes when a deploy of the fixed commit goes live after the load
finishes and the live `/health` shows `rss_peak_mb` well under 512 at boot and
after one semantic `/chat`. Set the Health Check Path to `/ready` before the
next push.

## Deploys since 799aa7a fail at startup

Production still runs d051b37 (2026-08-15). Render built the next two commits,
799aa7a (2026-09-14) and 7423445 (2026-09-15), and both failed with "Exited
with status 3 while running your code". The live API therefore has no trend
labels and no round projections.

Commit 799aa7a removed `college_compass.db` from git and added `*.db` to
`.gitignore`. The backend reads its reference tables from that file at boot:
the `lifespan` hook in `api/main.py` calls `load_reference_tables()`, which
runs `SELECT * FROM colleges`. A fresh Render checkout has no database, so
startup raises and uvicorn exits with status 3.

Reproduced on 2026-10-21 from a clean extract of HEAD's tracked files
(`git archive`) with no database present. SQLite created an empty file and
startup failed:

    sqlite3.OperationalError: no such table: colleges
    [SQL: SELECT * FROM colleges]
      File "api/main.py", line 65, in lifespan
        reference_tables = load_reference_tables()
      File "api/eligibility.py", line 60, in load_reference_tables
        colleges = pd.read_sql("SELECT * FROM colleges", engine)
    pandas.errors.DatabaseError: Execution failed on sql 'SELECT * FROM colleges'
    ERROR:    Application startup failed. Exiting.

The process exit code was 3. The repository holds no Render configuration (no
`render.yaml`, `Procfile` or build script), so the build and start commands
exist only in the Render dashboard.

Fix, in code and not yet deployed: `scripts/fetch_db.py` downloads the
database from a GitHub release asset during the Render build, decompresses
it, and checks a pinned SHA-256. A failed download or a checksum mismatch
fails the build. A failed model load now also exits with status 3 after the
server has opened its port, so a bad database still fails the deploy. The
README sections "Build the database" and "The live deployment" carry the
steps.

The 2026-10-23 deploy of 5741275 fetched the database and started the service,
so this cause is fixed. That deploy then ran out of memory (previous entry).
This entry closes when a deploy of the fixed commit stays up and live
`/recommend` rows carry `trend` and `rounds`.

## Keep-warm job is disabled

The cron-job.org job "college-compass keep-warm" sends
`GET https://college-compass-il7k.onrender.com/health` every 5 minutes with a
30 second timeout. Its status is Inactive. The last run, on 2026-09-26, ended
in "Failed (HTTP error)" after 692 ms, and cron-job.org then disabled the job.
The execution history is past its retention window.

A 692 ms failure is a quick error response. That points at Render answering
with an error status during a restart or a failed redeploy. A slow cold start
would time out instead.

On 2026-10-21 `GET /health` returned 200 in 0.44 s. `HEAD /health` returned
405, because the route accepts only GET. A pinger set to HEAD would log that
as an HTTP error. The job is set to GET, so this is not shown to be the cause.

With the job off, the free instance sleeps when idle and the next visitor
waits through a cold boot with no message on screen. The README says the ping
runs every ten minutes. That becomes true when the job is re-enabled at the
new interval.

Fix, in code and not yet deployed: `/health` answers GET and HEAD while the
models load, reports `models_loaded: false` until they finish, and adds
`rss_mb` and `rss_peak_mb`. After a deploy succeeds, re-enable the job: GET
`/health`, every 10 minutes, 30 second timeout, failure notification on. The
job stays on `/health`; `/ready` is a separate route for Render's health check.
This entry closes once the job has run clean against the new deploy.

## A request during startup gets a bare 503

The backend now opens its port before the models finish loading. Any request
that needs a model gets a 503 ("models are still loading, try again shortly")
until the load completes. Before this change the same request waited for the
whole boot and then succeeded. The frontend shows the 503 message as an
ordinary error and the student has to retry. A waking-up screen with an
automatic retry is planned for the frontend polish phase.

## Requests answered during the background load raise boot memory on Windows

Measured on Windows on 2026-10-21, working set right after the models load.
Seven boots of the previous code read 250.8 to 252.5 MB. Loading the same
code synchronously reads about 250 MB, but nothing can be answered during a
synchronous load. With the background load, the reading depends on how many
requests the server answers while loading: 3 to 4 `/health` polls gave 252.4
and 257.7 MB, 31 to 36 polls gave 262.7 to 265.8 MB, and 48 to 54 polls gave
267.3 to 270.0 MB. Small request objects allocated beside the loader's large
ones appear to pin memory that the loader later frees. A real pinger and the
platform's port check send a handful of requests during a load, so the
expected cost is a few MB, not the 16 to 19 MB the densest harness runs showed.
Peak working set at boot was about 640 MB then and is about 322 MB after the
memory fix (first entry).

The Linux effect is not measured. The live `rss_mb` and `rss_peak_mb` on
Render's `/health` settle whether it matters for the 512 MB limit.

## Grounding validation checks membership in one flat pool, not per-field or per-college attribution

`validate_grounding` (`models/counsellor.py`) extracts every numeric token
the model states (`extract_numbers`) and checks whether that exact string
appears anywhere in `_grounded_value_strings(bundle)` - one flat set built
from every record's value across the whole context bundle (ranks,
probabilities, fees, semantic-match scores), plus every record's year and
the student's own stated inputs. It does not scope the check by field kind
or by which college/branch the model attributed the number to.

Concretely: if a context bundle covers several colleges (the normal case for
a semantic "colleges like X" question, which returns five), a number that is
genuinely grounded for college A's predicted closing rank would also pass
validation if the model mistakenly stated it as college B's closing rank, or
as college A's NIRF rank, or as a year. The validator only proves "this
number appears somewhere in real data", not "this number is the right kind
of value, attached to the right college". A same-value collision across
fields or colleges (e.g. two records that happen to share a digit-for-digit
value) would not be caught either.

Not fixed here - this is the optional grounding hardening named in the
project plan. A fix would scope `_grounded_value_strings` (or the comparison
in `validate_grounding`) per record kind (`predicted_closing_rank` vs
`nirf_rank` vs `fees_annual_lakhs` vs `year`) and ideally per college_id, so
a rank-context number can only validate against a rank value for the college
the model is talking about. Deferred because it changes the shape of the
core grounding check - a product invariant - so it needs a deliberate pass
with its own test coverage, not a quiet change folded into a deploy-readiness
phase.

## Strip-and-retry can mangle a legitimate number that shares digits with an ungrounded one

`_strip_ungrounded` (`models/counsellor.py`) removes an ungrounded number by
running `re.sub(re.escape(n), "[figure not available in the system's
data]", stripped)` for each ungrounded number `n` across the entire answer
text, not just the specific spot where it appeared. If a short ungrounded
number is also a substring of an unrelated, correctly-grounded number
elsewhere in the same answer, that unrelated number gets corrupted too,
even though it individually passed `validate_grounding`.

Concretely, seen in the captured Phase 0 baseline
(`tests/fixtures/baseline/chat_semantic_fuzzy.json`): the model's answer
used a markdown numbered list ("1. Check your own rank... 2. Compare your
rank... 3. Decide which specialisation..."). `extract_numbers` correctly
flags the bare list markers 1, 2, 3 as ungrounded - they are not real
system values. But 2 is also a substring of the real, grounded forecast
year 2025, and 3 is a substring of several real, grounded closing ranks
(39655, 39676, 30755). Stripping 2 and 3 globally turned 2025 into
"[figure not available in the system's data]0[figure not available in the
system's data]5" and 39655 into "[figure not available in the system's
data]9655" in the final answer - both were genuine, grounded numbers
before the strip pass ran.

Not fixed here - stripping is meant to run after grounding has already
been decided, so a fix needs to replace only the specific occurrence
flagged as ungrounded (by span, not by global substring), not touch every
other digit-match in the text. That is a targeted change to
`_strip_ungrounded`, worth its own pass with test coverage rather than a
drive-by edit inside a deploy-focused phase.

## Grounded counsellor's context can exceed a free-tier provider's per-minute token limit

Verified against a real hosted LLM (Groq, `openai/gpt-oss-120b`) on
2026-07-18. Four question types were manually tested against `POST /chat`:

- Structured/forecast (named college + student profile, e.g. "predicted
  closing rank and admission chance at IIT Bombay Environmental Science and
  Engineering" for rank 5000 OPEN): returned a real generated answer citing
  the predicted closing rank, band, and calibrated admission probability,
  all matching the retrieved context exactly. `blocked_ungrounded_figure`
  was `false`.
- Semantic/fuzzy ("comparable colleges to top IITs with a strong CS
  reputation"): returned real FAISS similarity matches with scores, all
  grounded and correctly cited.
- Placement question ("average placement package and starting salary at IIT
  Bombay CS"): declined with the fixed placement-decline message, before
  ever reaching the LLM.
- Out-of-scope general question ("capital of France / when did WW2 end"):
  the model correctly refused and stayed in JoSAA/JEE Main scope, per the
  system prompt.

One real failure mode surfaced during testing: a "mixed" question that both
names a college and asks for alternatives (e.g. "colleges similar to IIT
Delhi") pulls the named college's full historical per-branch closing-rank
history plus five semantically similar colleges' data into one context. That
prompt (about 8,477 tokens) exceeded Groq's free/on-demand tier limit of
8,000 tokens per minute, and the call failed with a 413 `rate_limit_exceeded`
from the provider. `models/counsellor.py`'s `except Exception` catches this
the same way as a genuinely unreachable endpoint and returns the same clean
"not reachable" message - correct in that it never fabricates an answer, but
the message doesn't distinguish "the server is down" from "the provider
rejected this request as too large." A pure semantic question with no named
college (no per-branch history attached) stayed under the limit and
succeeded normally.

Not something to fix silently: shrinking the context bundle is a change to
what the grounding validator can cite from, so it needs a deliberate call
rather than a quiet patch. Options for later: split a "mixed" question into
two smaller LLM calls, cap historical branches attached per named college,
or note in the UI that a paid tier / larger-context provider avoids this.
For now, on a paid tier or a provider without an aggressive per-minute token
cap, this does not happen.

The retry-on-ungrounded-number path and answer-quality/naturalness were not
separately stress-tested beyond the four calls above, since none of the four
real answers ever contained an ungrounded figure to strip.

## Counsellor college-name matching can resolve "IIIT X" to "IIT X"

Found while capturing README screenshots on 2026-07-18, not a code change
made in that pass. `models/counsellor_retrieval.py`'s alias generator
(`_college_aliases`) only recognizes "Indian Institute of Information
Technology" as the IIIT name prefix. A handful of real IIITs are officially
named "International Institute of Information Technology" instead (e.g.
IIIT Bhubaneswar), so no short alias ("iiit bhubaneswar") ever gets
registered for them - only their full canonical name does.

That gap turns into a wrong match, not just a missed one: `_match_college`
picks the longest registered alias that appears as a substring of the
question. "iiit bhubaneswar" (the student's actual question, lowercased)
contains "iit bhubaneswar" as a substring, which *is* a registered alias -
for the unrelated Indian Institute of Technology Bhubaneswar. Asking "what's
the closing rank for CS at IIIT Bhubaneswar" silently resolves to IIT
Bhubaneswar instead, and the counsellor gives a grounded, data-accurate
answer about the wrong college.

Not fixed here. A fix needs either a second IIIT prefix ("International
Institute of Information Technology") in `_INSTITUTE_TYPE_PREFIX`, or a
word-boundary check in `_match_college` instead of plain substring
containment, so "iiit" never silently matches on an "iit" substring. Small,
contained fix, but changes matching behavior for every question, so it
deserves its own pass with test coverage rather than a drive-by edit.

## 2023 and 2024 cutoffs have no round breakdown, and cannot be backfilled from any source already in the pipeline

Confirmed during the Phase 1 round-backfill probe (forecast-depth upgrade).
Every year 2016-2022 carries a real per-round series in the `cutoffs` table;
2023 and 2024 carry exactly one row per key, with `round` null on all of
them. This is not a normalizer bug: it traces to the source each year is
actually fetched from.

- 2016-2020: `fetch_josaa_rounds` (`data_pipeline/ingest.py:42`) pulls
  seshaljain/josaa-scrape's per-round CSVs. Confirmed live against that
  repo's GitHub API listing: it only ever published 2016-2020.
- 2021-2022: `fetch_full_2021_2022` (`data_pipeline/ingest.py:87`, read by
  `_read_full_2021_2022()` in `data_pipeline/normalize.py:206`) pulls a CSV
  named `2016-2023dataa.csv` that does carry real Year/Round columns. The
  filename overpromises: the file has zero rows for 2023 (`grep -c "^2023,"`
  on the raw file returns 0 out of 312,400 rows), so `FULL_2021_2022_MAX_YEAR
  = 2022` in `data_pipeline/sources.py:47` is already the true ceiling of
  this source, not an arbitrary cutoff.
- 2023: `fetch_snapshot_2023` (`data_pipeline/ingest.py:98`, read by
  `_read_snapshot_2023()` in `data_pipeline/normalize.py:268`) pulls a sqlite
  snapshot from Sbrjt/josaa-cutoffs. Its `tb` table has no Year or Round
  column at all (confirmed by direct schema introspection of the downloaded
  `data/raw/snapshot_2023/db.sqlite3`) - `normalize.py:284` sets `Round =
  pd.NA` because there is nothing to read, not because it discards one.
- 2024: `fetch_josaa_2024` (`data_pipeline/ingest.py:65`, read by
  `_read_josaa_2024()` in `data_pipeline/normalize.py:198`) pulls
  Quantum-Codes/JoSAA_2024's `josaa24.csv`. Confirmed by direct inspection:
  the raw CSV has 7 columns (Institute, Academic Program Name, Quota, Seat
  Type, Gender, Opening Rank, Closing Rank) and no Round column in the source
  itself. Same reason for `Round = pd.NA` in `normalize.py:201`.

**Deferred, per the Phase 1 hard-stop rule.** None of the four sources
already wired into the pipeline exposes round-wise data for 2023 or 2024.
Backfilling would need a fifth source: a public, no-auth repository
publishing JoSAA's round-wise 2023 and/or 2024 closing ranks, verified the
same way `full_2021_2022` and `snapshot_2023` were (cross-checked against a
few institutes' own published PDFs before being trusted - see
`data_pipeline/sources.py`), plus a new `fetch_*`/`_read_*` pair following
the existing pattern and a rerun of `normalize.py` and the Phase 0 coverage
audit. That is a new-source search and a verification pass, not a
straightforward reuse of what already exists, so it is out of scope for a
single phase and stays deferred until someone goes looking for that fifth
source.

This is binding on the round feature: Phase 5 and Phase 6's held-out year
must keep coming from 2016-2022, exactly as Phase 0 already concluded.

## Postgres schema has no indexes beyond the ones SQLAlchemy creates for PK/FK (closed for production)

Closed 2026-10-21 as not applicable to production: the live service runs
SQLite from the release database, and no Render Postgres exists, so there is
no Postgres instance to time. The measurement script stays for anyone who
moves to Postgres later.

**Partially addressed (Phase 2, forecast-depth upgrade).** `db/models.py` now
declares `ix_cutoffs_college_program_category_quota`, a composite index on
`cutoffs(college_id, program_id, category, quota)` matching the WHERE-clause
column order in both `get_cutoff_history()` and `get_cutoff_history_bulk()`
(`api/main.py`). `db/generate_schema_sql.py` now emits `CREATE INDEX`
statements too (it previously only emitted `CREATE TABLE`), so `db/schema.sql`
carries the index for a fresh Postgres bootstrap.

**Dev SQLite: created and measured.** `EXPLAIN QUERY PLAN` on the same lookup
now reports `SEARCH cutoffs USING INDEX ix_cutoffs_college_program_category_
quota`, not `SCAN cutoffs`. Timed with `db/measure_cutoff_index.py` against
the same 672-key candidate set Phase 1 used (a cold, non-pooled connection
each time, not an average of warm repeat calls): 450.1 ms before the index,
360.2-426.9 ms after across repeat runs. A real improvement, smaller than the
index alone might suggest, because the settled-round selection is a window
function (`ROW_NUMBER() OVER (PARTITION BY ... )`) over the filtered rows,
which still has to run after the index narrows the scan.

**Postgres: not measured, and not needed for production.**
`db/measure_cutoff_index.py` takes its target from the `DATABASE_URL`
environment variable only, never a command-line argument, so a connection
string never lands in shell history:

    DATABASE_URL=postgresql://user:pass@host:5432/dbname python -m db.measure_cutoff_index

The script is idempotent (`checkfirst=True` on the index creation) and
otherwise read-only, but the index is a plain `CREATE INDEX`, which blocks
writes to `cutoffs` while it builds. Run it against a copy or in a quiet
window, not against a live instance under traffic.

**No longer gates the trend classifier (Phase 2, updated 2026-09-14).**
`/recommend` no longer calls `get_cutoff_history_bulk()` per request at all
- `build_cutoff_history_cache()` (api/main.py) builds the whole settled
history table once per process, lazily, and every request after the first
is a dict lookup. The Postgres connection latency this entry was tracking
only matters for the one-time cache build (and for `/cutoffs`'s single-key
lookups, which were never the bottleneck), not for `/recommend`'s
per-request cost. The index is still worth having and this number is still
worth knowing, but it is informational now, not a blocker.

## college_compass.db tracked in git (closed)

Closed 2026-10-21. Commit 799aa7a removed `college_compass.db` from git, and
`.gitignore` now lists `*.db`, so a fresh clone no longer carries the 100 MB
binary. The same change removed the only copy of the database that a deploy
could reach, and production deploys have failed since. See "Deploys since
799aa7a fail at startup".
