"""Three-arm evaluation of the counsellor's grounding behaviour over the fixed
question set (tests/fixtures/eval/counsellor_questions.json).

  A  validator off: the model's first answer, as it came.
  B  validator, one retry, strip the figure, no note (the behaviour before Phase 4).
  C  validator, one retry, strip, and the verification note (the behaviour now).

Every check is deterministic code; no model grades any answer. Two limits come
with that. The production validator (`_ungrounded_spans`) is also the instrument,
so arms B and C, whose output it has already stripped, read zero on the first two
metrics by construction; only arm A shows what the model says unprompted, and a
figure the validator wrongly accepts is invisible here (the Phase 3 and 4a sweeps
measure that). And "useful after rejection" is the question file's definition
read by fixed phrase lists written from the note's own wording, so it measures
whether an answer carries the note's content, not whether a student was helped.
The arms run
through generate_answer with its evaluation-only switches, over one shared set
of provider completions: the first answer to a question is fetched once and
replayed to all three arms, and the retry is fetched once and replayed to C, so
the arms differ only in what they do with the same text. Real calls are spaced
at least `--delay` seconds apart (the free tier allows 8,000 tokens a minute).

Run (laptop only; this module is never imported by the API):

    python -I models/eval_counsellor.py --run eval_run.jsonl
    python -I models/eval_counsellor.py --rescore eval_run.jsonl
    python -I models/eval_counsellor.py --report eval_run.jsonl

--run appends one JSON line per finished question and skips the questions
already in the file, so an interruption or a provider daily limit resumes where
it stopped. --rescore scores every recorded question again from its recorded
completions with the code as it is now, without asking the provider, so a change
to the scoring does not cost a new run; the committed results are always
--rescore then --report. --report writes tests/fixtures/eval/counsellor_results.json.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from models import counsellor as cm  # noqa: E402

# The scoring code the records were scored with (line endings do not count).
CODE_HASH = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]
QUESTIONS_PATH = ROOT / "tests" / "fixtures" / "eval" / "counsellor_questions.json"
RESULTS_PATH = ROOT / "tests" / "fixtures" / "eval" / "counsellor_results.json"
# The one set, in the two line endings it is read with: the Windows checkout
# converts the committed LF file to CRLF (36,885 bytes), a Linux checkout or CI
# reads it as committed (35,827 bytes). Either is the frozen set.
QUESTIONS_SHA256 = {
    "a649f169054e941f6ef5d055527f097d946b8a248c0fb72338977dc6ce0f1e6f": "CRLF",
    "b7847f275f3ec227022a5f90ac3fc61e82e158fb7c6eb9e870099722cc162e67": "LF",
}
DEFAULT_DELAY = 60
ARMS = {"A": {"validate": False, "escalate": False}, "B": {"validate": True, "escalate": False}, "C": {"validate": True, "escalate": True}}
CLASSES = ("verifiable", "near_miss", "unverifiable", "mixed", "placement")
# V10 cannot be answered by any arm (the branch matcher misreads "Computer Science"
# for IIIT Allahabad), so it is reported apart and left out of its class and the total.
SEPARATE = ("V10",)

# Fixed phrase lists for the two "useful after rejection" checks that read words
# (the question file: "checked by fixed phrase lists committed with the harness").
SAYS_UNVERIFIED = ("could not verify", "cannot verify", "can't verify", "unable to verify", "not available in the system", "not on record", "no record of")
SAYS_NOTHING_CLOSE = ("nothing close", "no close figure", "nothing similar")
NAMES_NEXT_STEP = (
    "name it and give your category",
    "name a college",
    "name the college",
    "ask about one college",
    "give your category",
    "give your rank and category",
)


def verify_question_set():
    """The set is hashed and never edited: refuse to run against a changed file."""
    data = QUESTIONS_PATH.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest not in QUESTIONS_SHA256:
        raise SystemExit(f"question set changed: sha256 {digest} is neither of {sorted(QUESTIONS_SHA256)}")
    return json.loads(data)["questions"]


# --- the provider, shared between arms -------------------------------------------------------


class DailyLimit(Exception):
    """The provider's per-day token limit, not the per-minute one: stop the run."""


class ProviderUnreachable(Exception):
    """The provider could not be reached: a network fault, not an answer. Stop
    the run without recording the question, so a resume asks it again.
    """


def _is_daily_limit(exc):
    text = str(exc).lower()
    return "per day" in text or "tpd" in text


class Pacer:
    def __init__(self, seconds):
        # A resumed run starts mid-minute: the provider counts the previous process's last call.
        self.seconds, self.last = seconds, time.monotonic()

    def wait(self):
        time.sleep(max(0.0, self.seconds - (time.monotonic() - self.last)))

    def done(self):
        self.last = time.monotonic()


class Stored:
    """The recorded completions of one finished question, in the order they were
    asked for (None is a provider refusal), for --rescore.
    """

    def __init__(self, completions):
        self.items = list(completions)
        self.chat = self.completions = self

    def create(self, model, messages, temperature=0.2):
        if not self.items:
            raise LookupError("the recorded completions ran out")
        text = self.items.pop(0)
        if text is None:
            raise openai.RateLimitError("recorded refusal", response=httpx.Response(429, request=httpx.Request("POST", "http://recorded")), body=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class Replay:
    """Stands in for the OpenAI client. A request is sent to the provider once;
    an identical request from another arm gets the same completion, or the same
    refusal, back.
    """

    def __init__(self, client, pacer):
        self.client, self.pacer = client, pacer
        self.cache, self.texts, self.daily_limit = {}, [], False
        self.chat = self.completions = self

    def create(self, model, messages, temperature=0.2):
        key = json.dumps([messages, temperature], sort_keys=True)
        if key not in self.cache:
            self.pacer.wait()
            try:
                response = self.client.chat.completions.create(model=model, messages=messages, temperature=temperature)
                self.cache[key] = ("ok", response)
                self.texts.append(response.choices[0].message.content or "")
            except Exception as exc:  # generate_answer decides what a failure means
                self.cache[key] = ("error", exc)
                self.texts.append(None)
                self.daily_limit = self.daily_limit or _is_daily_limit(exc)
            self.pacer.done()
        kind, value = self.cache[key]
        if kind == "error":
            raise value
        return value

    @property
    def calls(self):
        return len(self.texts)


# --- scoring ---------------------------------------------------------------------------------


def _figure_spans(text, bundle):
    """The numbers in text that are figures: not a year of a record, a round, a
    program length or one of the student's own inputs. As (value, start, end).
    """
    years = {str(r["year"]) for r in bundle["records"] if r.get("year")}
    inputs = cm._input_value_strings(bundle)
    rounds = {m.start(1) for m in cm.ROUND_PATTERN.finditer(text)}
    lengths = {s for s, _ in cm._program_lengths(text)}
    return [(n, s, e) for n, s, e in cm.extract_numbers(text) if s not in rounds and s not in lengths and n not in years and n not in inputs]


def _held(value, bundle):
    grounded = cm._grounded_value_strings(bundle)
    return value in grounded or value.rstrip("%") in grounded


def _says(text, phrases):
    low = text.lower().replace("’", "'")
    return any(p in low for p in phrases)


def _states_fields(text, figure, bundle):
    """Whether text names the college, branch, program, category, seat pool, year
    and round of an expected figure, the way the labels and the note write them.
    """
    low = text.lower()

    def mentions(phrase, strict=False):
        """A whole word or phrase; strict also stops at "(", "/" and "-" ("OPEN (PwD)" is not OPEN)."""
        before, after = (r"[a-z0-9(/-]", r"[a-z0-9]|\s*[(/-]") if strict else (r"[a-z0-9]", r"[a-z0-9]")
        return bool(phrase) and re.search(rf"(?<!{before}){re.escape(phrase.lower())}(?!{after})", low) is not None

    names = [bundle.get("college_names", {}).get(figure["college_id"], "")] + bundle.get("college_aliases", {}).get(figure["college_id"], [])
    digit = re.match(r"(\d)-year", figure["program"])
    round_ = f"round {figure['round']}" in low if figure["round"] is not None else "no round data" in low
    return (
        any(mentions(n) for n in names)
        and mentions(figure["branch"])
        and bool(digit) and digit.group(1) in {d for _, d in cm._program_lengths(text)}
        and mentions(figure["category"], strict=True)
        and ("gender-neutral" in low or "gender neutral" in low)
        and mentions(str(figure["year"]))
        and round_
    )


def _useful_after_rejection(question, bundle, text):
    """The four conditions of the question file's definition, in code."""
    if cm._ungrounded_spans(text, bundle):
        return False
    if not _says(text, SAYS_UNVERIFIED) or not _says(text, NAMES_NEXT_STEP):
        return False
    closest = question["closest_figures"]
    stated = {n for n, _, _ in _figure_spans(text, bundle)}
    if not closest:
        return not stated and _says(text, SAYS_NOTHING_CLOSE)
    return len(stated) == 1 and any(str(f["value"]) in stated and _states_fields(text, f, bundle) for f in closest)


def score_arm(arm, question, bundle, result, first_rejected):
    """One arm's result for one question: what happened and the three checks."""
    answer = result["answer"]
    if bundle["mode"] == "out_of_scope_placement":
        return {"outcome": "placement_decline" if answer == cm.PLACEMENT_DECLINE_ANSWER else "placement_wrong", "answered": True}
    if answer in (cm.PROVIDER_REJECTED_ANSWER, cm.LLM_UNREACHABLE_ANSWER):
        kind = "refused" if answer == cm.PROVIDER_REJECTED_ANSWER else "unreachable"
        refusal = {"outcome": f"{kind}_retry" if result["blocked_ungrounded_figure"] else f"{kind}_first", "answered": False}
        return {**refusal, "useful": False} if first_rejected else refusal

    verification = result.get("verification")
    text = answer + (" " + verification["message"] if verification else "")
    flagged = cm._ungrounded_spans(text, bundle)
    outcome = "clean"
    if first_rejected:
        if arm == "A":
            outcome = "unvalidated"
        elif verification:
            outcome = "closest" if verification["closest"] else "nothing_close"
        else:
            outcome = "stripped" if result["blocked_ungrounded_figure"] else "recovered"
    score = {
        "outcome": outcome,
        "answered": True,
        "unsupported": any(not _held(n, bundle) for _, _, n in flagged),
        "attribution_error": any(_held(n, bundle) for _, _, n in flagged),
        "states_held_figure": any(_held(n, bundle) for n, _, _ in _figure_spans(text, bundle)),
    }
    if first_rejected:
        score["useful"] = _useful_after_rejection(question, bundle, text)
    return score


def run_question(question, bundle, client, pacer):
    """All three arms for one question over one shared set of completions."""
    replay = Replay(client, pacer)
    original = cm._client
    cm._client = lambda: replay
    try:
        results = {arm: cm.generate_answer(question["question"], bundle, **switches) for arm, switches in ARMS.items()}
    finally:
        cm._client = original
    if replay.daily_limit:
        raise DailyLimit(question["id"])
    first = replay.texts[0] if replay.texts else None
    first_rejected = None if first is None else bool(cm._ungrounded_spans(first, bundle))
    arms = {}
    for arm, result in results.items():
        arms[arm] = score_arm(arm, question, bundle, result, first_rejected)
    faults = [v for kind, v in replay.cache.values() if kind == "error" and not cm._provider_refused(v)]
    if faults or any(a["outcome"].startswith("unreachable") for a in arms.values()):
        raise ProviderUnreachable(f"{question['id']}: {type(faults[0]).__name__ if faults else 'blank completion'}")
    return {
        "id": question["id"],
        "class": question["class"],
        "first_rejected": first_rejected,
        "scored_by": CODE_HASH,
        "provider_calls": replay.calls,
        "completions": replay.texts,
        "answers": {arm: {"answer": r["answer"], "verification": r.get("verification")} for arm, r in results.items()},
        "arms": arms,
    }


# --- the report ------------------------------------------------------------------------------


def _cell(rows):
    answered = [r for r in rows if r["answered"]]
    held = [r for r in answered if r.get("states_held_figure")]
    rejected = [r for r in rows if "useful" in r]
    return {
        "questions": len(rows),
        "answered": len(answered),
        "refused": sum(r["outcome"].startswith(("refused", "unreachable")) for r in rows),
        "unsupported": [sum(r.get("unsupported", False) for r in answered), len(answered)],
        "attribution_error": [sum(r.get("attribution_error", False) for r in held), len(held)],
        "rejected": len(rejected),
        "useful": [sum(r["useful"] for r in rejected), len(rejected)],
        "outcomes": {o: sum(r["outcome"] == o for r in rows) for o in sorted({r["outcome"] for r in rows})},
    }


def summarize(records):
    """Per arm, per class and overall: the three metrics as [count, base] pairs
    and the outcome counts. V10 is reported apart. Only questions the provider
    answered the first call for count as rejected or not.
    """
    tables = {}
    for arm in ARMS:
        counted = [r for r in records if r["id"] not in SEPARATE]
        by_class = {c: _cell([r["arms"][arm] for r in counted if r["class"] == c]) for c in CLASSES}
        # Placement never states a figure, so it would only dilute the rates: its own row, outside the total.
        tables[arm] = {**by_class, "overall": _cell([r["arms"][arm] for r in counted if r["class"] != "placement"])}
    apart = {r["id"]: {"first_rejected": r["first_rejected"], **{arm: r["arms"][arm] for arm in ARMS}} for r in records if r["id"] in SEPARATE}
    return {
        "questions_sha256": sorted(QUESTIONS_SHA256),
        "questions_run": len(records),
        "provider_calls": sum(r["provider_calls"] for r in records),
        "first_answers_rejected": sum(bool(r["first_rejected"]) for r in records if r["id"] not in SEPARATE),
        "tables": tables,
        "reported_apart": apart,
        "per_question": {r["id"]: {"class": r["class"], "first_rejected": r["first_rejected"], **{arm: r["arms"][arm] for arm in ARMS}} for r in records},
    }


def _pct(pair):
    k, n = pair
    return f"{k}/{n}" if n == 0 else f"{k}/{n} ({100 * k / n:.0f}%)"


def render(summary):
    lines = []
    for metric, label in (("unsupported", "Unsupported claim rate"), ("attribution_error", "Attribution error rate"), ("useful", "Useful after rejection")):
        lines += ["", f"{label}", "| Class | A | B | C |", "| --- | --- | --- | --- |"]
        for c in (*CLASSES, "overall"):
            lines.append(f"| {c} | " + " | ".join(_pct(summary["tables"][arm][c][metric]) for arm in ARMS) + " |")
    lines += ["", "Refused or unreachable (not counted as answers)", "| Class | A | B | C |", "| --- | --- | --- | --- |"]
    for c in (*CLASSES, "overall"):
        lines.append(f"| {c} | " + " | ".join(str(summary["tables"][arm][c]["refused"]) for arm in ARMS) + " |")
    lines += ["", "Outcomes per class"]
    for c in (*CLASSES, "overall"):
        lines.append(f"- {c}: " + "; ".join(f"{arm} {summary['tables'][arm][c]['outcomes']}" for arm in ARMS))
    lines.append(f"- first answers rejected (V10 excluded): {summary['first_answers_rejected']}; provider calls: {summary['provider_calls']}")
    return "\n".join(lines)


# --- the run ---------------------------------------------------------------------------------


def _write_records(path, records):
    """Write the run file whole or not at all: it holds the only copy of the paid completions."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    tmp.replace(path)


def _wait_loaded(http):
    deadline = time.monotonic() + 300
    while not http.get("/health").json()["models_loaded"]:
        if time.monotonic() > deadline:
            raise SystemExit("the app did not finish loading in 300 s")
        time.sleep(0.5)


def _load_done(path):
    if not path.exists():
        return {}
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    records = []
    for i, line in enumerate(lines):
        try:
            record = json.loads(line)
            record["id"]
        except (json.JSONDecodeError, TypeError, KeyError):
            if i < len(lines) - 1:
                raise  # a damaged line in the middle is not a crash mid-write
        else:
            records.append(record)
    return {r["id"]: r for r in records}


def _order(questions):
    """Placement first (no provider call), then one question of each class in
    turn, so a run cut short by the daily limit still covers every class.
    """
    queues = {c: [q for q in questions if q["class"] == c] for c in CLASSES}
    ordered = list(queues.pop("placement"))
    while any(queues.values()):
        ordered += [queue.pop(0) for queue in queues.values() if queue]
    return ordered


def run(path, delay, only):
    questions = [q for q in verify_question_set() if not only or q["id"] in only]
    done = _load_done(path)
    if path.exists():  # drops a last line a crash cut off, so the next append starts on a fresh line
        _write_records(path, done.values())
    todo = _order([q for q in questions if q["id"] not in done])
    calls = sum(q["class"] != "placement" for q in todo)
    print(f"{len(done)} done, {len(todo)} to run, about {calls} first calls plus a retry for each rejected answer, {delay} s apart", flush=True)

    from fastapi.testclient import TestClient
    import api.main as api_main  # loads .env, then the models, as in production
    from models.counsellor_retrieval import build_context_bundle

    client = cm._client().with_options(timeout=120.0)
    pacer = Pacer(delay)
    with TestClient(api_main.app) as http:
        _wait_loaded(http)
        first_refusals = 0
        for q in todo:
            bundle = build_context_bundle(q["question"], q["student_profile"], api_main.model_state)
            try:
                record = run_question(q, bundle, client, pacer)
            except ProviderUnreachable as fault:
                print(f"provider call failed at {fault}, not a rate limit; the question is not recorded. {len(done)} of {len(questions)} done. Resume with the same command once it is fixed.", flush=True)
                return 4
            except DailyLimit:
                print(f"provider daily limit reached at {q['id']}; {len(done)} of {len(questions)} done. Resume with the same command tomorrow.", flush=True)
                return 3
            done[q["id"]] = record
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            first_refusals = first_refusals + 1 if record["arms"]["A"]["outcome"].startswith("refused_first") else 0
            if first_refusals == 3:
                print("three first calls in a row were refused: the provider is limiting this key. Resume later with the same command.", flush=True)
                return 3
            print(f"{q['id']} {q['class']}: rejected={record['first_rejected']} calls={record['provider_calls']} " + " ".join(f"{a}={r['outcome']}" for a, r in record["arms"].items()), flush=True)
    return 0


def _rescored(question, bundle, old):
    """One question scored again from its recorded completions. The recording is
    kept as it is: if the current code asks for other completions than were
    recorded, nothing is rewritten.
    """
    try:
        new = run_question(question, bundle, Stored(old["completions"]), Pacer(0))
    except ProviderUnreachable as fault:
        raise SystemExit(f"{question['id']}: the recorded completions do not cover what the current code asks for ({fault}); nothing was rewritten")
    if new["completions"] != old["completions"]:
        raise SystemExit(f"{question['id']}: the current code asked for fewer completions than were recorded; nothing was rewritten")
    return {**new, "provider_calls": old["provider_calls"]}


def rescore(path):
    """Score every recorded question again from its recorded completions and
    rewrite the run file (a .bak copy first), printing each arm result the new
    code reads differently. Do not run it while a --run is alive.
    """
    records = _load_done(path)
    if not records:
        raise SystemExit(f"no finished questions in {path}")
    from fastapi.testclient import TestClient
    import api.main as api_main
    from models.counsellor_retrieval import build_context_bundle

    questions = {q["id"]: q for q in verify_question_set()}
    rescored = {}
    with TestClient(api_main.app) as http:
        _wait_loaded(http)
        for qid, old in records.items():
            q = questions[qid]
            bundle = build_context_bundle(q["question"], q["student_profile"], api_main.model_state)
            rescored[qid] = _rescored(q, bundle, old)
            for arm in ARMS:
                if rescored[qid]["arms"][arm] != old["arms"][arm]:
                    print(f"{qid} arm {arm}: {old['arms'][arm]} -> {rescored[qid]['arms'][arm]}")
    path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
    _write_records(path, rescored.values())
    records = rescored
    print(f"rescored {len(records)} questions")


def report(path):
    records = list(_load_done(path).values())
    if not records:
        raise SystemExit(f"no finished questions in {path}; the results file was not touched")
    stale = [r["id"] for r in records if r.get("scored_by") != CODE_HASH]
    if stale:
        raise SystemExit(f"{len(stale)} questions were scored by other code ({', '.join(stale[:4])}...); run --rescore first")
    expected = len(verify_question_set())
    summary = {**summarize(records), "scored_by": CODE_HASH, "complete": len(records) == expected}
    RESULTS_PATH.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(render(summary))
    print(f"\nwrote {RESULTS_PATH.relative_to(ROOT)} ({len(records)} of {expected} questions{'' if summary['complete'] else ', INCOMPLETE'})")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run", type=Path, help="append results to this JSONL file and resume from it")
    parser.add_argument("--rescore", type=Path, help="score this JSONL file's recorded completions again with the current code")
    parser.add_argument("--report", type=Path, help="write the committed results file from this JSONL file")
    parser.add_argument("--delay", type=int, default=DEFAULT_DELAY, help="seconds between real provider calls")
    parser.add_argument("--only", default="", help="comma-separated question ids")
    args = parser.parse_args(argv)
    if args.run:
        return run(args.run, args.delay, {i for i in args.only.split(",") if i})
    if args.rescore:
        return rescore(args.rescore)
    if args.report:
        return report(args.report)
    verify_question_set()
    print("question set verified; pass --run or --report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
