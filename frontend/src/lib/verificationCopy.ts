import type { Verification, VerificationFigure } from "./api";

// What the verification note says, apart from how it looks so the wording and
// the two states can be checked without rendering. The sentences are the
// backend templates (models/counsellor.py ESCALATION_*, pinned by
// tests/test_counsellor_escalation.py): the note splits the closest figure into
// parts so the college and branch and the rank can be styled, and reads back as
// the backend's message except that the value is grouped the Indian way.

export const NOTE_LEAD = "I removed a figure I could not verify. The closest figure on record is for";
export const NOTE_NEXT_STEP = "To check another college or branch, name it and give your category.";

// The JoSAA quota codes in words, as models/counsellor.py QUOTA_NAMES.
const QUOTA_WORDS = new Map([["AI", "All India"], ["HS", "Home State"], ["OS", "Other State"]]);
const KIND_WORDS: Record<VerificationFigure["kind"], string> = {
  actual_closing_rank: "closing rank",
  predicted_closing_rank: "forecast closing rank",
};

export type NoteContent =
  | { state: "closest"; place: string; program: string; facts: string; kind: string; value: string }
  | { state: "nothing_close"; text: string };

// Absent verification means no note. A closest figure shows all of its
// attribution; without one the note is the backend's single plain statement
// and never a figure.
export function noteContent(verification: Verification | null | undefined): NoteContent | null {
  if (!verification) return null;
  const f = verification.closest;
  // A closest figure that is missing a part cannot be shown as one: the backend's own sentence stands in for it.
  const whole = f && Number.isFinite(f.value) && Number.isFinite(f.year) && [f.college_name, f.branch, f.program, f.category, f.pool, f.quota].every((part) => typeof part === "string" && part);
  if (!f || !whole) return verification.message ? { state: "nothing_close", text: verification.message } : null;
  return {
    state: "closest",
    place: `${f.college_name}, ${f.branch}`,
    program: f.program,
    facts: [f.category, `${f.pool} seats`, `${QUOTA_WORDS.get(f.quota) ?? f.quota} quota`, String(f.year), f.round == null ? "no round data" : `round ${f.round}`].join(", "),
    kind: KIND_WORDS[f.kind],
    value: f.value.toLocaleString("en-IN"),
  };
}
