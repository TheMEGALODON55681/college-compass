# Known issues

## Grounded counsellor's live-generation path is unverified against a real LLM

`POST /chat` (`models/counsellor.py`) has never been run end to end against a
real language model. No local LLM server (Ollama, LM Studio, etc.) or hosted
API key was available in the environment where it was built and tested.

What is verified:
- The numeric grounding validator (`validate_grounding`) is unit-tested,
  including a case where a fabricated rank survives a retry and gets
  stripped rather than shown (`tests/test_counsellor_grounding.py`).
- The unreachable-endpoint path is tested against a real dead port (not
  mocked) and confirmed to return a clean error, never a fabricated answer.
- Structured/semantic retrieval routing is verified directly (correct
  college matched, correct numbers returned).

What is NOT verified:
- Whether a real model stays within the system prompt's scope
  (JoSAA/JEE Main only, no placement questions, no general-knowledge
  answers) when talking to an actual LLM rather than a scripted fake
  response.
- Whether real generated answers read naturally and are useful, since no
  real answer has ever been produced.
- Whether the retry-on-ungrounded-number path behaves as expected against a
  real model's actual failure modes (a real LLM may fail differently than
  the fabricated-number test fixtures do).

This must be checked against a live LLM endpoint before the counsellor is
exposed to real students. Set `LLM_ENDPOINT` and `LLM_MODEL` to a running
OpenAI-compatible server and manually test a range of questions (structured,
semantic, placement, out-of-scope) before relying on it.

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
