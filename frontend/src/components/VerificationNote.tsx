import { C, fBody, fMono } from "../lib/tokens";
import type { Verification } from "../lib/api";
import { NOTE_LEAD, NOTE_NEXT_STEP, noteContent } from "../lib/verificationCopy";

// docs/Design.md, VerificationNote: shown inside a counsellor answer whose
// figure could not be verified. A quiet cool panel, no alert colour or icon,
// no entrance of its own (the answer bubble already animates in). The
// attribution is the content, in ink700 at body size with the rank in mono. The
// program length ("four-year") never splits across lines.
// Absent `verification` renders nothing (docs/Rules.md section 8's
// additive-field contract). The live region is the message list in
// screens/Counsellor.tsx, which exists before the note is added.
export function VerificationNote({ verification }: { verification: Verification | null | undefined }) {
  const content = noteContent(verification);
  if (!content) return null;

  const length = content.state === "closest" ? content.program.match(/^(\S+-year)(.*)$/s) : null;
  const text = { fontFamily: fBody, fontSize: 14, lineHeight: 1.55, color: C.ink700, margin: 0 } as const;
  return (
    <div role="note" style={{ marginTop: 12, padding: "10px 12px", background: C.washCool, border: `1px solid ${C.line}`, borderRadius: 10 }}>
      {content.state === "nothing_close" ? (
        <p style={text}>{content.text}</p>
      ) : (
        <>
          <p style={text}>
            {NOTE_LEAD}{" "}
            <strong style={{ fontWeight: 600, color: C.ink900 }}>
              {content.place} ({length ? <><span style={{ whiteSpace: "nowrap" }}>{length[1]}</span>{length[2]}</> : content.program})
            </strong>
            , {content.facts}: {content.kind}{" "}
            <span style={{ fontFamily: fMono, fontWeight: 500, fontSize: 15, color: C.ink900 }}>{content.value}</span>.
          </p>
          <p style={{ ...text, marginTop: 6 }}>{NOTE_NEXT_STEP}</p>
        </>
      )}
    </div>
  );
}
