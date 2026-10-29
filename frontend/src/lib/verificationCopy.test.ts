// Runnable check for verificationCopy.ts, same pattern as roundCopy.test.ts:
// plain assertions, no test framework, run with
// `node src/lib/verificationCopy.test.ts`.

import type { Verification } from "./api.ts";
import { NOTE_LEAD, NOTE_NEXT_STEP, noteContent, type NoteContent } from "./verificationCopy.ts";

function check(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

// The note as one run of text, in the order the component reads it.
function noteText(content: NoteContent): string {
  if (content.state === "nothing_close") return content.text;
  return `${NOTE_LEAD} ${content.place} (${content.program}), ${content.facts}: ${content.kind} ${content.value}. ${NOTE_NEXT_STEP}`;
}

// The two objects below are what models/counsellor.py _escalation returns for
// IIT Delhi Computer Science (a fabricated 99999 stripped twice), with and
// without a close record on file.
const WITH_FIGURE: Verification = {
  outcome: "escalate",
  unverified_count: 1,
  closest: {
    college_id: "indian-institute-of-technology-delhi",
    college_name: "Indian Institute of Technology Delhi",
    branch: "Computer Science and Engineering",
    program: "four-year BTech",
    category: "OPEN",
    pool: "Gender-Neutral",
    quota: "AI",
    year: 2024,
    round: null,
    kind: "actual_closing_rank",
    value: 116,
  },
  message:
    "I removed a figure I could not verify. The closest figure on record is for Indian Institute of Technology Delhi, Computer Science and Engineering (four-year BTech), OPEN, Gender-Neutral seats, All India quota, 2024, no round data: closing rank 116. To check another college or branch, name it and give your category.",
};

const NOTHING_CLOSE: Verification = {
  outcome: "escalate",
  unverified_count: 1,
  closest: null,
  message:
    "I removed a figure I could not verify, and nothing close to it is on record. Ask about one college and one branch, with your category, and I will check the data.",
};

// No verification, no note: also when the backend sends null.
check(noteContent(undefined) === null, "undefined verification should give no note");
check(noteContent(null) === null, "null verification should give no note");

// A closest figure: every attribution field is in the text, the quota in
// words, and it reads back as the backend's own message.
{
  const content = noteContent(WITH_FIGURE);
  check(content?.state === "closest", `expected the closest state, got ${content?.state}`);
  check(noteText(content!) === WITH_FIGURE.message, `closest text drifted from the backend message:\n${noteText(content!)}`);
  const text = noteText(content!);
  for (const part of ["Indian Institute of Technology Delhi", "Computer Science and Engineering", "four-year BTech", "OPEN", "Gender-Neutral seats", "All India quota", "2024", "no round data", "116"]) {
    check(text.includes(part), `closest text is missing ${part}`);
  }
  check(!/\bAI\b/.test(text), "the quota code AI should be spelled out");
}

// Nothing close: the backend's one plain statement, and no digit.
{
  const content = noteContent(NOTHING_CLOSE);
  check(content?.state === "nothing_close", `expected the nothing-close state, got ${content?.state}`);
  check(noteText(content!) === NOTHING_CLOSE.message, "nothing-close text should be the backend message");
  check(!/\d/.test(noteText(content!)), "nothing-close text must not hold a figure");
}

// A round, a forecast figure, a home-state quota and a rank in the thousands.
{
  const content = noteContent({ ...WITH_FIGURE, closest: { ...WITH_FIGURE.closest!, round: 3, quota: "HS", kind: "predicted_closing_rank", value: 125000 } });
  const text = noteText(content!);
  check(text.includes("round 3"), "a round should read as round 3");
  check(text.includes("Home State quota"), "HS should read as Home State");
  check(text.includes("forecast closing rank 1,25,000"), `expected a forecast rank in Indian grouping, got: ${text}`);
}

// An unknown quota code is shown as it came rather than dropped.
{
  const content = noteContent({ ...WITH_FIGURE, closest: { ...WITH_FIGURE.closest!, quota: "JK" } });
  check(noteText(content!).includes("JK quota"), "an unknown quota code should pass through");
}

// A payload that is not what the type says must still give a note, never throw.
{
  const noValue = noteContent({ ...WITH_FIGURE, closest: { ...WITH_FIGURE.closest!, value: null as unknown as number } });
  check(noValue?.state === "nothing_close" && noteText(noValue) === WITH_FIGURE.message, "a closest figure with no value should fall back to the backend message");
  check(noteContent({ ...NOTHING_CLOSE, message: "" }) === null, "an empty message should give no note");
  for (const [part, bad] of [["value", Number.NaN], ["program", undefined], ["quota", undefined], ["year", null]] as const) {
    const broken = noteContent({ ...WITH_FIGURE, closest: { ...WITH_FIGURE.closest!, [part]: bad } as never });
    check(broken?.state === "nothing_close", `a closest figure with a bad ${part} should fall back to the backend message`);
  }
  const noRound = noteContent({ ...WITH_FIGURE, closest: { ...WITH_FIGURE.closest!, round: undefined as unknown as null } });
  check(noteText(noRound!).includes("no round data"), "a missing round should read as no round data");
  const odd = noteContent({ ...WITH_FIGURE, closest: { ...WITH_FIGURE.closest!, quota: "constructor" } });
  check(noteText(odd!).includes("constructor quota"), "an inherited object key is not a quota name");
}

console.log("ok");
