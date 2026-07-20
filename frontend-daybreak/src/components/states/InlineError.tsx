import { C, fBody } from "../../lib/tokens";

// Neutral by design: Design.md reserves the Likely/Fair/Reach colors for
// probability meaning only, so an error never borrows the Reach coral.
export function InlineError({ message }: { message: string }) {
  return (
    <p
      role="alert"
      style={{
        fontFamily: fBody, fontSize: 14, color: C.ink700, lineHeight: 1.6,
        background: C.paper, border: `1px solid ${C.line}`,
        borderRadius: 10, padding: "12px 16px", marginTop: 12,
      }}
    >
      {message}
    </p>
  );
}
