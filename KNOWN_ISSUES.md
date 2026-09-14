# Known issues

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

## Postgres schema has no indexes beyond the ones SQLAlchemy creates for PK/FK

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

**Postgres: not yet measured.** No Postgres instance or credentials are
available in the environment these phases run in. `db/measure_cutoff_index.py`
is written and ready - it takes its target from the `DATABASE_URL`
environment variable only, never a command-line argument, so a connection
string never lands in shell history:

    DATABASE_URL=postgresql://user:pass@host:5432/dbname python -m db.measure_cutoff_index

It is idempotent (`checkfirst=True` on the index creation) and read-only
otherwise, so it's safe to run against the real Render Postgres instance
directly. The developer can still run this and report the numbers back for
the record; this entry stays open until then.

**No longer gates the trend classifier (Phase 2, updated 2026-09-14).**
`/recommend` no longer calls `get_cutoff_history_bulk()` per request at all
- `build_cutoff_history_cache()` (api/main.py) builds the whole settled
history table once per process, lazily, and every request after the first
is a dict lookup. The Postgres connection latency this entry was tracking
only matters for the one-time cache build (and for `/cutoffs`'s single-key
lookups, which were never the bottleneck), not for `/recommend`'s
per-request cost. The index is still worth having and this number is still
worth knowing, but it is informational now, not a blocker.

## college_compass.db is tracked in git

Found during Phase 2's repo-hygiene check (forecast-depth upgrade),
2026-09-14: `git ls-files --error-unmatch college_compass.db` confirms the
file is tracked, not ignored. It is currently 101.5MiB on disk and grows
with every reingest (60.3MiB before the most recent one, per `git diff
--stat`).

A binary SQLite file in git history bloats the repository on every clone,
makes every schema change an opaque diff instead of a reviewable one, and
lets the tracked database silently drift from what `db/schema.sql` actually
describes, since nothing enforces that the two stay in sync.

Not fixed here. Untracking it (`git rm --cached college_compass.db` plus a
`.gitignore` entry) is a git write, and per docs/Rules.md section 2 that is
the developer's to run, not something to do automatically. Flagged
directly to the developer this session as well.
