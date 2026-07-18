# Known issues

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

## Postgres schema has no indexes beyond the ones SQLAlchemy creates for PK/FK

The SQLite-to-Postgres migration (`db/migrate_to_postgres.py`) is a straight
substrate swap - same tables, same columns, same keys, same query behavior.
It does not add any Postgres-specific indexes (e.g. on `cutoffs(college_id,
program_id)` or `cutoffs(year, gender_seat_type)`, which the regressor's
training queries filter on heavily) beyond what SQLAlchemy's own primary/
foreign key definitions already create. Adding those would very likely speed
up Postgres reads, but it's a performance change, not a substrate swap, so it
was deliberately left out of this migration rather than folded in. Worth
doing as its own follow-up once the app is running on Postgres in a setting
where query latency matters.
