import { motion } from "motion/react";
import { C, fBody, fDisplay, fMono } from "../../lib/tokens";
import { Eyebrow } from "../Eyebrow";

// Zero eligible college-branches at all, for any band. Distinct from the
// care state (CareStateBlock), which covers few-or-no Likely while Fair or
// Reach options still exist. Invites a fix, never blames the student.
export function EmptyState({ onAdjust }: { onAdjust: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.56 }}
      style={{
        maxWidth: 1160,
        margin: "0 auto",
        background: `linear-gradient(135deg, ${C.washWarm} 0%, ${C.signatureTint} 100%)`,
        borderRadius: 14,
        border: `1px solid ${C.line}`,
        padding: "40px 32px",
      }}
    >
      <Eyebrow style={{ color: C.signature, marginBottom: 12 }}>Your shortlist</Eyebrow>
      <h2 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: "clamp(20px, 4vw, 26px)", color: C.ink900, margin: "0 0 14px", letterSpacing: "-0.01em" }}>
        No eligible colleges landed for this exact profile yet.
      </h2>
      <p style={{ fontFamily: fBody, fontSize: 16, color: C.ink700, lineHeight: 1.72, marginBottom: 28, maxWidth: 560 }}>
        A small change often opens real options: a broader branch or college-type pick, turning off
        the home-state preference, or double-checking the rank you entered.
      </p>
      <button
        onClick={onAdjust}
        style={{
          fontFamily: fBody, fontSize: 14, fontWeight: 600,
          color: C.primary, background: C.primaryTint,
          border: "none", borderRadius: 10, padding: "11px 20px", cursor: "pointer", minHeight: 44,
        }}
      >
        Adjust your rank card
      </button>
      <div style={{ fontFamily: fMono, fontSize: 10, color: C.ink500, letterSpacing: "0.06em", marginTop: 20 }}>
        Nothing was invented to fill this gap - this is the real result for what you entered.
      </div>
    </motion.div>
  );
}
