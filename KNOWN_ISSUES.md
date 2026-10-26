# Known issues

## A deploy goes live, then runs out of memory at boot (closed)

On 2026-10-23 Render built commit 5741275, fetched the database from the
`db-v1` release and reported the service live at 22:34 IST. Within a minute it
logged "Ran out of memory (used over 512MB) while running your code", again at
22:35, and then restarted about every 90 seconds. `/health` returned an error
page. Render refused the rollback to d051b37 ("could not roll back", the free
tier no longer kept that build), so the site stayed down until the fix shipped.

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

Fix, commit 6b2259c:

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
384 to 389 MB, lifetime peak 409 to 412 MB. There was no local Linux run under a 512 MB
cap: Docker is not installed on the development laptop.

Closed 2026-10-26. With the Health Check Path set to `/ready`, the deploy of
6b2259c answered 503 during the load and 200 after, and Render reported it live
only then. Live `/health` readings: after a cold wake `rss_mb` 328.3 and
`rss_peak_mb` 363.6; after another cold wake 318.0 and 352.7; awake a day later
323.6 and 367.5. The peak sits about 150 MB under the 512 MB limit, so the
precomputed forecast frame stays unbuilt. Still to take: a live reading after
one semantic `/chat`.

## Deploys since 799aa7a fail at startup (closed)

Production ran d051b37 (2026-08-15) while Render built the next two commits,
799aa7a (2026-09-14) and 7423445 (2026-09-15), and both failed with "Exited
with status 3 while running your code". The live API therefore had no trend
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

Fix: `scripts/fetch_db.py` downloads the database from a GitHub release asset
during the Render build, decompresses it, and checks a pinned SHA-256. A failed
download or a checksum mismatch fails the build. A failed model load also exits
with status 3 after the server has opened its port, so a bad database still
fails the deploy. The README sections "Build the database" and "The live
deployment" carry the steps.

Closed 2026-10-26. The build log of the 6b2259c deploy shows `fetch_db`
verifying the `db-v1` asset, and the service went live.

## Keep-warm job is disabled (closed)

The cron-job.org job "college-compass keep-warm" sent
`GET https://college-compass-il7k.onrender.com/health` every 5 minutes with a
30 second timeout. The last run, on 2026-09-26, ended in "Failed (HTTP error)"
after 692 ms, and cron-job.org then disabled the job. The execution history is
past its retention window.

A 692 ms failure is a quick error response. That points at Render answering
with an error status during a restart or a failed redeploy. A slow cold start
would time out instead.

On 2026-10-21 `GET /health` returned 200 in 0.44 s. `HEAD /health` returned
405, because the route accepts only GET. A pinger set to HEAD would log that
as an HTTP error. The job is set to GET, so this is not shown to be the cause.

With the job off, the free instance sleeps when idle and the next visitor
waits through a cold boot with no message on screen.

Fix: `/health` answers GET and HEAD while the models load, reports
`models_loaded: false` until they finish, and adds `rss_mb` and `rss_peak_mb`.
`/ready` is a separate route for Render's health check.

Closed 2026-10-26. The developer recreated the job: GET
`https://college-compass-il7k.onrender.com/health`, every 10 minutes, 30 second
timeout, failure notifications on. It has returned 200 OK since 10:10 IST that
day. See the next entry for what to do if it is ever paused.

## A sleeping Render instance answers with its own 503 page

On Render free, a sleeping instance answers every request with Render's own
"waking up" 503 page until the service has started, and a short ping can fail
to start it. If the keep-warm job is ever paused, open the site once in a
browser and wait for it to load before turning the job back on. The job must
use https: the http address returns a 301 redirect, which cron-job.org counts
as a failure.

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

On Linux the live `rss_mb` after boot read 318.0 to 328.3 MB with a peak of
352.7 to 367.5 MB (2026-10-26), so whatever the effect is there, it leaves the
512 MB limit well clear.

## Grounding validation checks membership in one flat pool, not per-field or per-college attribution (closed)

`validate_grounding` (`models/counsellor.py`) used to extract every number the
model stated and accept it if that exact string appeared anywhere in one flat
set: every record's value across the bundle, every record's year, and the
student's own inputs. It did not look at which college or which kind of figure
the answer gave the number to. A semantic question like "colleges like X"
returns five colleges, so a real closing rank for college A passed when the
model stated it as college B's, as a NIRF rank, or in the wrong year.

Closed 2026-10-26 (Phase 3). The flat set stays as the first gate, so every
number the old check rejected is still rejected. A number that passes it is
then judged against the records its sentence points at. Each rank and
probability record now carries `program_id`, `branch`, `category`, `quota`,
`pool` and `round`, and the bundle carries each college's aliases. The
validator cuts the answer into segments (a line, a sentence, or a clause after
a semicolon). A segment's college, year, branch, category, seat pool and round
apply to the numbers inside it, and a cue word beside a number ("closing
rank", "NIRF", "fees", "probability") says which kind of figure it is. The
number must be a value of a record that agrees on everything the segment
states. A segment that names no college falls back to every college in the
bundle, and a number with no cue word may be any kind of value. A "round 3"
must be a round of a record for that college. The retry message now tells the
model a number may be missing or attached to the wrong college, year,
category, round or kind. Tests: `tests/test_counsellor_attribution.py`. A
sweep of 12,762 faithful sentences built from every college's real records
(three phrasings each) flagged none apart from the case in the last entry.

## Grounding is judged one sentence at a time

Left open by Phase 3 on purpose. The validator treats a segment as a set, so a
sentence that names two colleges, or two categories, accepts either figure
for either: "IIT Delhi and IIT Bombay have closing ranks of 116 and 68" passes
with the figures swapped. Telling the two apart reliably means parsing English
clause structure, and a stricter rule would block faithful answers written as
"A and B have X and Y". Splitting at semicolons catches the swap when the
model writes two clauses. Eight more limits:

- A branch is read only by its full name as the records spell it. "CSE" and
  "Computer Science" name no branch, so a Computer Science rank given for
  Mechanical in the same college passes unless the sentence uses the full name.
- A quota is never read, because "AI" is also a branch abbreviation. A category
  is read only in capitals as the API spells it (OPEN, OBC-NCL).
- A number equal to a year in the bundle counts as that year wherever it
  appears, so a closing rank of exactly 2024 is not attributed. The old flat
  check had the same property.
- A rank stated with no branch, category, year or round still passes when the
  college and value match. The rule that a figure must carry all six fields
  before the student sees it belongs to the escalation work in Phase 4.
- A branch name with an abbreviation in it, such as "Integrated B. Tech. - M.
  Tech in Civil Engineering", is cut at its full stops. The segment that holds
  the figure then names no branch, year or category, so the validator checks
  none of them.
- A college name that contains a branch name counts as naming that branch.
  "Indian Institute of Information Technology" names Information Technology,
  so at that college a figure written beside "Information
  Technology-Business Informatics" can pass with the plain Information
  Technology rank.
- A cue word is read on the left of a figure first, and a cue on the right
  counts only when none sits on the left. "NIRF ranks IIT Delhi high, 204 is
  the closing rank for OPEN" reads 204 as a NIRF rank and flags it, though the
  nearer cue says closing rank. The error runs toward a false reject.
- The N in "round N" passes when any record of the named college has that
  round, whatever its branch, category or year.

## A college name that contains digits fails the grounding check

Found 2026-10-26 by the Phase 3 sweep, and older than Phase 3. One canonical
name carries a postal code: "North Eastern Regional Institute of Science and
Technology, Nirjuli-791109 (Itanagar),Arunachal Pradesh". If the model writes
the full name, 791109 is in no record, so the check flags it, the answer goes
back for a retry it did not need, and a retry that keeps the name strips the
digits out of it. A fix would skip numbers that sit inside a college name or
alias. Not fixed: it is outside Phase 3 and touches one college.

## Strip-and-retry can mangle a legitimate number that shares digits with an ungrounded one (closed)

Closed 2026-10-26 (Phase 2). `_strip_ungrounded` ran one global `re.sub` per
flagged number, so a flagged 3 also rewrote the 3 inside a genuine 39655, and a
flagged 2 turned the year 2025 into "[figure not available in the system's
data]0[figure not available in the system's data]5". The captured baseline
answer (`tests/fixtures/baseline/chat_semantic_fuzzy.json`) shows it: the model
numbered its steps, the validator flagged the markers 1, 2 and 3 as ungrounded,
and stripping them corrupted real ranks and the year. The same code had a
second flaw. A flagged figure written with a thousands separator ("12,345") was
searched for as "12345", never found, and stayed in an answer the system
reported as blocked.

`extract_numbers` now returns each number with its span, and `_strip_ungrounded`
replaces only those spans, so neither failure can happen. Bare list ordinals
(one or two digits at the start of a line, followed by "." or ")", with or
without bold markers) no longer count as figures: they are formatting, they
forced a pointless retry, and a model cannot slip a rank through one. A real
figure inside a list item is still checked. Tests:
`tests/test_counsellor_strip.py`.

## Grounded counsellor's context can exceed a free-tier provider's per-minute token limit (closed)

Found 2026-07-18 against a real hosted LLM (Groq, `openai/gpt-oss-120b`). A
question that names a college and asks for alternatives ("colleges similar to
IIT Delhi") attached the named college's whole cutoff history, 201 rows, next
to five similar colleges. That prompt came to about 8,477 tokens, over the free
tier's 8,000 tokens per minute, and the provider answered 413. The counsellor
treated every exception as an unreachable endpoint and said the language model
was not reachable. That was wrong: the provider was up and had refused the
request.

Closed 2026-10-26 (Phase 2), in two parts. A provider 413 or 429 now gets its
own fixed answer ("I couldn't answer that. The language model service behind
the counsellor refused this request: it was too long, or the service hit its
usage limit. Wait a minute and ask again, or ask about one college and one
branch."), distinct from the unreachable message and free of numbers. A
connection failure still reads as unreachable. And a mixed question now
attaches at most `MIXED_HISTORY_ROW_CAP` (120; 90 and renamed `SHARED_HISTORY_ROW_CAP` from Phase 3b) history rows for the named
college, OPEN rows first so every branch keeps its OPEN row, in a fixed order.
At 3.4 characters per token (the ratio the 8,477-token report implies for the
29,058-character prompt) the largest prompt over every college in the database
was about 6,280 tokens (6,189 once Phase 3 limited the history to Gender-Neutral
rows). A live check on the free tier answered "colleges similar
to IIT Delhi" in 1.7 s. Tests: `tests/test_counsellor_provider.py`,
`tests/test_counsellor_context_size.py`.

Phase 3 shrank the case that stayed open after Phase 2. A question about one
college with no student profile and no request for alternatives ("closing ranks
for IIT Delhi") attaches every row and stays uncapped on purpose. Limiting the
history to Gender-Neutral seats cut IIT Delhi's prompt from about 8,400 to about
4,800 tokens. Over the 101 colleges a canonical-name question matches, the median
is about 1,600 tokens and the largest is IIT Patna at about 7,200 (149 rows), so
none reaches 8,000 by the same 3.4 characters-per-token estimate. Two questions
inside one minute can still draw a refusal from a free tier.

If the provider refuses the stricter retry (sent after an ungrounded figure),
the student still gets the first answer with that figure stripped, not the
refusal message.
The retry path gets its stress test in Phase 4.

## Counsellor college-name matching can resolve "IIIT X" to "IIT X" (closed)

Closed 2026-10-26 (Phase 2). Two defects combined. The alias builder keyed its
short names ("iiit bhubaneswar") on the database's `institute_type`, and four
colleges whose names say Institute of Information Technology are GFTI in
that column: International Institute of Information Technology Bhubaneswar and Naya
Raipur, and Indian Institute of Information Technology Raichur and Senapati
Manipur. They never got a short alias. And `_match_college` used plain
substring containment, so "iit bhubaneswar" matched inside "iiit bhubaneswar"
and the counsellor answered, with grounded data, about the wrong college.

Short names now come from the canonical name, matched against four phrases (IIT,
NIT and both IIIT spellings), and an alias only matches as whole words. The
alias map before and after differs by four new aliases, and every
question built from an existing alias resolves to the same college as before. Tests:
`tests/test_counsellor_matching.py`.

## Historical closing ranks mix seat pools and carry no pool or round (closed)

Found 2026-10-26 while sizing the Phase 2 history cap.
`_historical_closing_ranks` (`models/counsellor_retrieval.py`) selected a
college's rows for its latest year and one quota with no filter on
`gender_seat_type`, and its labels named the branch, year, quota and category
but not the seat pool or the round. For IIT Delhi, 2024, quota AI, that was 201
rows: 112 Gender-Neutral and 89 Female-only. A branch and category appeared
once per pool, with different closing ranks and the same label, so with no
student profile the counsellor could state a Female-only rank as the OPEN rank.
It broke the Gender-Neutral-only rule and the rule that every stated figure
carries college, branch, category, seat pool, year and round.

Closed 2026-10-26 (Phase 3). The query keeps Gender-Neutral rows only and takes
the latest year that has such rows, so IIT Delhi's history is 112 rows. The same
query had a second flaw. Seven colleges whose latest data is a per-round year
(2019 to 2022) attached a row for every round under one label, so round 1 and
round 6 ranks for the same branch and category looked identical. The query now
keeps the final round, the row `/cutoffs` shows, and the label names the round
when the year has one. Each record carries its pool and round. The other cutoff
readers were checked and hold the rule: the forecast reads Gender-Neutral rows
in SQL, and `/cutoffs`, the trend cache and the bulk history exclude Female-only
rows. They keep the 2016 and 2017 "Not gender-split" rows on purpose, since
JoSAA did not split seats before 2018. The 120-row cap stayed in Phase 3 (Phase 3b lowered it to 90): the largest mixed
prompt over every college is now 6,189 tokens (IIT Patna), where 130 rows would
give 6,620 and 140 rows 7,014. Tests: `tests/test_counsellor_seat_pool.py`.

## A counsellor question with a rank gets no closing ranks for branches the rank cannot reach (closed)

Found 2026-10-26 on the live site. A student with a rank card asked for the
closing rank of Computer Science at IIT Delhi, and the counsellor answered that
the records did not include it. The database holds fifteen 2024 rows for that
branch. With a student profile, the counsellor built a college's records from
the eligibility filter alone, and that filter lists only the branches the
student can reach. A rank of 12,480 reaches none of IIT Delhi's Computer Science
rows, so the model received a NIRF rank and a fee and nothing else, and said so.
The same gap opened for a branch written as "CSE", which the counsellor does not
read as a branch: a student who could reach other IIT Delhi branches got those
forecasts and no Computer Science row. The behavior predates Phase 3: the code at
`93dbe3d` builds the same two records and gives the same refusal, and the IIT
Bombay baseline fixtures pin the same empty bundle.

Closed 2026-10-26 (Phase 3b). A college the question names now always carries its
latest Gender-Neutral closing ranks, the rows a question without a profile gets,
and a profile adds its forecast rows beside them. Two limits keep the prompt
under the provider's token limit. The history is capped at 90 rows whenever it
shares the prompt with a profile's forecast rows or with alternatives (the cap
was 120 for alternatives), OPEN rows first; no college has more than 32 OPEN
rows, so every branch keeps its OPEN row. And a question that also asks for
alternatives ("colleges similar to IIT Delhi") attaches the history only for a
student who cannot reach the college, because the five neighbours' forecast rows
leave no room for both. A student who can reach it gets the forecast, as before.
Over 133 colleges, 16 profiles and two phrasings, the worst prompt is 5,391
tokens for a one-college question and 6,644 for one with alternatives; uncapped
they were 7,880 and 8,707. A college listed as an alternative still shows only
what the student can reach. Two golden fixtures that pinned the empty bundle,
`chat_structured_named_college` and `chat_grounding_stress_extrapolation`, now
list the IIT Bombay rows. Tests: `tests/test_counsellor_out_of_reach.py`.

## Four colleges with only 2016 or 2017 data have an empty counsellor history

Found 2026-10-26 while reviewing the Phase 3 seat-pool filter.
`_historical_closing_ranks` keeps Gender-Neutral rows, and JoSAA did not split
seats by gender before 2018, so rows from 2016 and 2017 carry the pool "Not
gender-split". Four of the 133 colleges have no row from 2018 on: Indian School
of Mines Dhanbad, Indian Institute of Crop Processing Technology Thanjavur, and
two spellings of IIIT Sri City. A counsellor question about one of them gets a
NIRF rank and a fee and no closing ranks. Before Phase 3 the same question got
their 2016 or 2017 rows. None of the four reaches the forecast, so no
recommendation lists them.

Left open on purpose: serving those rows takes a second seat-pool rule, with
each record keeping its real pool, and that is a policy call.

## Numbers written with a space between digit groups split into fragments

Seen in the 2026-10-26 live check. The model answered with closing ranks
grouped by a narrow no-break space ("39 655"). `NUMBER_PATTERN` reads "39" and
"655" as two numbers, neither is in the bundle, so the check flagged both and
sent the answer back for a retry it did not need. The retry returned the plain
"39655" and passed, so the student saw a correct answer after an extra provider
call. If a retry keeps the grouping, the strip replaces each fragment on its
own and the check blocks a real rank. No fabricated figure gets through; it
errs toward blocking. Not fixed: it sits outside the four Phase 2 bugs. A fix
would extend `NUMBER_PATTERN` to join digit groups separated by a space or a
narrow no-break space, and test it against the grounded set.

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
