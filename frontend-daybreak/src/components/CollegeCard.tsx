import { useState } from "react";
import { motion } from "motion/react";
import { MapPin } from "lucide-react";
import { C, STATUS, easeOut, fBody, fDisplay, fMono, shadow } from "../lib/tokens";
import type { College } from "../lib/types";
import { formatLocation } from "../lib/adapters";
import { StatusPill } from "./StatusPill";
import { ProbabilityMeter } from "./ProbabilityMeter";

export function CollegeCard({ college, index, onDetail, studentRank }: {
  college: College; index: number; onDetail: (c: College) => void; studentRank: number;
}) {
  const [hovered, setHovered] = useState(false);
  const [saved, setSaved] = useState(false);
  const s = STATUS[college.status];

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.15 }}
      transition={{ delay: index * 0.06, duration: 0.56, ease: easeOut }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: C.surface, borderRadius: 14, border: `1px solid ${C.line}`,
        padding: "22px 24px",
        boxShadow: hovered ? shadow.raised : shadow.rest,
        transform: hovered ? "translateY(-2px)" : "translateY(0)",
        transition: "box-shadow 160ms, transform 160ms",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14, gap: 10, flexWrap: "wrap" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
            <span style={{ fontFamily: fDisplay, fontSize: 17, fontWeight: 600, color: C.ink900 }}>{college.name}</span>
            <span style={{
              fontFamily: fMono, fontSize: 10, color: C.primary, background: C.primaryTint,
              padding: "2px 8px", borderRadius: 6, letterSpacing: "0.08em", textTransform: "uppercase",
            }}>{college.type}</span>
          </div>
          <div style={{ fontFamily: fBody, fontSize: 14, color: C.ink700, marginBottom: 2 }}>{college.branch}</div>
          {formatLocation(college) && (
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <MapPin size={12} color={C.ink300} />
              <span style={{ fontFamily: fBody, fontSize: 13, color: C.ink500 }}>{formatLocation(college)}</span>
            </div>
          )}
        </div>
        <StatusPill status={college.status} />
      </div>

      <div style={{ marginBottom: 14 }}>
        <div style={{ fontFamily: fMono, fontSize: 10, color: C.ink500, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>Admission probability</div>
        <ProbabilityMeter probability={college.probability} status={college.status} delay={index * 60} />
      </div>

      <div style={{
        display: "flex", gap: 24, padding: "10px 14px",
        background: C.paper, borderRadius: 8, marginBottom: 14, flexWrap: "wrap",
      }}>
        <div>
          <div style={{ fontFamily: fMono, fontSize: 10, color: C.ink500, letterSpacing: "0.08em", textTransform: "uppercase" }}>Your rank</div>
          <div style={{ fontFamily: fMono, fontSize: 18, fontWeight: 500, color: C.ink900 }}>{studentRank.toLocaleString("en-IN")}</div>
        </div>
        <div>
          <div style={{ fontFamily: fMono, fontSize: 10, color: C.ink500, letterSpacing: "0.08em", textTransform: "uppercase" }}>Expected closing</div>
          <div style={{ fontFamily: fMono, fontSize: 18, fontWeight: 500, color: C.ink700 }}>{college.closingRank.toLocaleString("en-IN")}</div>
        </div>
      </div>

      <p style={{ fontFamily: fBody, fontSize: 13, color: C.ink500, lineHeight: 1.65, marginBottom: 16 }}>{college.why}</p>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button onClick={() => onDetail(college)} style={{
          fontFamily: fBody, fontSize: 13, fontWeight: 600,
          color: C.primary, background: C.primaryTint,
          border: "none", borderRadius: 10, padding: "9px 18px", cursor: "pointer", minHeight: 44,
        }}>See details</button>
        <button onClick={() => setSaved(!saved)} style={{
          fontFamily: fBody, fontSize: 13, fontWeight: 600,
          color: saved ? s.text : C.ink500,
          background: saved ? s.tint : C.paper,
          border: `1px solid ${saved ? s.solid : C.line}`,
          borderRadius: 10, padding: "9px 18px", cursor: "pointer", minHeight: 44,
          transition: "all 160ms cubic-bezier(0.34, 1.4, 0.64, 1)",
        }}>
          {saved ? "Saved" : "Save to shortlist"}
        </button>
      </div>
    </motion.div>
  );
}
