import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { C, easeOut, fBody, fDisplay, fMono, shadow } from "../lib/tokens";
import { MINI_RANK_CARD_DEMOS, MINI_RANK_CARD_FIELDS } from "../lib/mockData";
import { StatusPill } from "./StatusPill";
import { ProbabilityMeter } from "./ProbabilityMeter";

// Hero demo card. Fields and matches are illustrative, not the live student.
export function MiniRankCard() {
  const [go, setGo] = useState(false);
  useEffect(() => { const t = setTimeout(() => setGo(true), 500); return () => clearTimeout(t); }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: 32 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.7, ease: easeOut }}
      style={{
        background: C.surface, borderRadius: 14,
        border: `1px solid ${C.line}`, boxShadow: shadow.signature, overflow: "hidden",
      }}
    >
      <div style={{
        background: `linear-gradient(135deg, ${C.signatureTint} 0%, ${C.primaryTint} 100%)`,
        padding: "18px 22px 14px", borderBottom: `1px solid ${C.line}`,
        display: "flex", justifyContent: "space-between", alignItems: "flex-start",
      }}>
        <div>
          <div style={{ fontFamily: fMono, fontSize: 10, color: C.primary, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 4 }}>
            College Compass · Rank Card
          </div>
          <div style={{ fontFamily: fDisplay, fontSize: 18, fontWeight: 600, color: C.ink900 }}>Your Shortlist</div>
        </div>
        <div style={{ fontFamily: fMono, fontSize: 9, color: C.ink300, textAlign: "right", lineHeight: 1.5 }}>
          CC-2026<br />JEE-012480
        </div>
      </div>

      <div style={{ padding: "14px 22px", borderBottom: `1px solid ${C.line}` }}>
        {MINI_RANK_CARD_FIELDS.map((f, i) => (
          <motion.div
            key={f.label}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: go ? 1 : 0, x: go ? 0 : -6 }}
            transition={{ delay: 0.1 + i * 0.07, duration: 0.35 }}
            style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "5px 0",
              borderBottom: i < MINI_RANK_CARD_FIELDS.length - 1 ? `1px solid ${C.line}` : "none",
            }}
          >
            <span style={{ fontFamily: fMono, fontSize: 10, color: C.ink500, letterSpacing: "0.08em", textTransform: "uppercase" }}>{f.label}</span>
            <span style={{ fontFamily: f.label === "CRL Rank" ? fMono : fBody, fontSize: 13, fontWeight: 600, color: C.ink900 }}>{f.value}</span>
          </motion.div>
        ))}
      </div>

      <div style={{ padding: "14px 22px" }}>
        <div style={{ fontFamily: fMono, fontSize: 10, color: C.ink500, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>Your matches</div>
        {MINI_RANK_CARD_DEMOS.map((d, i) => (
          <motion.div
            key={d.name + d.branch}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: go ? 1 : 0, y: go ? 0 : 8 }}
            transition={{ delay: 0.6 + i * 0.12, duration: 0.4 }}
            style={{ marginBottom: i < MINI_RANK_CARD_DEMOS.length - 1 ? 14 : 0 }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
              <div>
                <div style={{ fontFamily: fBody, fontSize: 12, fontWeight: 600, color: C.ink900 }}>{d.name}</div>
                <div style={{ fontFamily: fBody, fontSize: 11, color: C.ink500 }}>{d.branch}</div>
              </div>
              <StatusPill status={d.status} />
            </div>
            <ProbabilityMeter probability={d.prob} status={d.status} delay={900 + i * 150} />
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}
