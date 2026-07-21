import { motion } from "motion/react";
import { C, STATUS, fBody, fDisplay, fMono } from "../lib/tokens";
import type { College } from "../lib/types";
import { CollegeCard } from "./CollegeCard";

export function ResultGroup({ title, subtitle, count, colleges, onDetail, baseIndex, studentRank }: {
  title: string; subtitle: string; count: number;
  colleges: College[]; onDetail: (c: College) => void; baseIndex: number; studentRank: number;
}) {
  if (colleges.length === 0) return null;
  const s = STATUS[colleges[0].status];
  return (
    <div style={{ marginBottom: 52 }}>
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.2 }}
        transition={{ duration: 0.4 }}
        style={{ marginBottom: 20 }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <h3 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: 21, color: C.ink900, margin: 0 }}>{title}</h3>
          <span style={{
            fontFamily: fMono, fontSize: 11, color: s.text, background: s.tint,
            borderRadius: 999, padding: "3px 10px", letterSpacing: "0.06em",
          }}>{count}</span>
        </div>
        <p style={{ fontFamily: fBody, fontSize: 14, color: C.ink500, margin: 0 }}>{subtitle}</p>
        {colleges.length < count && (
          <p style={{ fontFamily: fMono, fontSize: 11, color: C.ink500, letterSpacing: "0.04em", margin: "6px 0 0" }}>
            Showing your top {colleges.length} of {count}, ordered by fit for you.
          </p>
        )}
      </motion.div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 16 }}>
        {colleges.map((c, i) => (
          <CollegeCard key={c.id} college={c} index={baseIndex + i} onDetail={onDetail} studentRank={studentRank} />
        ))}
      </div>
    </div>
  );
}
