import { motion } from "motion/react";
import { MessageCircle } from "lucide-react";
import { C, fBody, fDisplay, fMono } from "../lib/tokens";

const NEXT_STEPS = [
  { title: "JoSAA later rounds", desc: "Rounds 4, 5, and 6 often open seats that earlier rounds do not. Stay in the process through every round." },
  { title: "CSAB special rounds", desc: "After JoSAA closes, CSAB runs additional rounds for NIT+ seats - a real second chance." },
  { title: "State counselling", desc: "Your home state has its own counselling with separate seats and often softer cutoffs." },
  { title: "Other exams still open", desc: "BITSAT, state JEEs, and management quota routes are still ahead. None of these doors are closed." },
];

// Shown when likely.length === 0. The warmest screen in the product, not the bleakest.
export function CareStateBlock({ onCounsellor }: { onCounsellor: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.56 }}
      style={{
        background: `linear-gradient(135deg, ${C.washWarm} 0%, ${C.signatureTint} 100%)`,
        borderRadius: 14, border: `1px solid ${C.line}`,
        padding: "32px", marginBottom: 44,
      }}
    >
      <div style={{ fontFamily: fMono, fontSize: 11, color: C.signature, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>
        Your options
      </div>
      <h2 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: "clamp(20px, 4vw, 26px)", color: C.ink900, margin: "0 0 14px", letterSpacing: "-0.01em" }}>
        You have real options here. Let us start with your strongest ones, then look at what else is worth trying.
      </h2>
      <p style={{ fontFamily: fBody, fontSize: 16, color: C.ink700, lineHeight: 1.72, marginBottom: 28 }}>
        Your rank gives you genuine Fair chance options at good NITs. The colleges below are worth locking in seriously - not as fallbacks, but as real seats that students with your rank land. There is also a path forward through later rounds and other routes.
      </p>

      <div style={{ fontFamily: fMono, fontSize: 10, color: C.ink500, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>
        Doors still open
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, marginBottom: 28 }}>
        {NEXT_STEPS.map(step => (
          <div key={step.title} style={{
            background: C.surface, borderRadius: 10, padding: "14px 16px",
            border: `1px solid ${C.line}`,
          }}>
            <div style={{ fontFamily: fBody, fontWeight: 600, fontSize: 14, color: C.ink900, marginBottom: 5 }}>{step.title}</div>
            <div style={{ fontFamily: fBody, fontSize: 13, color: C.ink500, lineHeight: 1.6 }}>{step.desc}</div>
          </div>
        ))}
      </div>

      <button onClick={onCounsellor} style={{
        fontFamily: fBody, fontSize: 14, fontWeight: 600,
        color: C.primary, background: C.primaryTint,
        border: "none", borderRadius: 10, padding: "11px 20px", cursor: "pointer", minHeight: 44,
        display: "inline-flex", alignItems: "center", gap: 6,
      }}>
        <MessageCircle size={16} /> Ask the counsellor about your options
      </button>
    </motion.div>
  );
}
