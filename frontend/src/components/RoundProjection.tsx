import { motion, useReducedMotion } from "motion/react";
import { C, fBody, fMono, shadow } from "../lib/tokens";
import type { RoundProjectionPoint } from "../lib/api";
import { CROSSOVER_LABEL, EXPECTATION_LINE, findCrossoverIndex } from "../lib/roundCopy";
import { Eyebrow } from "./Eyebrow";

// docs/Design.md: rounds down the left, the student's own rank as one fixed
// reference rather than a value repeated per row, and a single point of
// emphasis on the row where the projection first reaches that rank - every
// other row stays quiet. Absent `rounds` renders nothing (docs/Rules.md
// section 7's additive-field contract): not an empty state, not an error.
export function RoundProjection({ rounds, studentRank }: { rounds: RoundProjectionPoint[] | null | undefined; studentRank: number }) {
  const reduceMotion = useReducedMotion();
  if (!rounds || rounds.length === 0) return null;

  const crossoverIndex = findCrossoverIndex(rounds, studentRank);

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }} transition={{ duration: 0.5, delay: 0.04 }}
      style={{ background: C.surface, borderRadius: 14, border: `1px solid ${C.line}`, padding: "28px", marginBottom: 20, boxShadow: shadow.rest }}
    >
      <Eyebrow style={{ marginBottom: 20 }}>Round projection</Eyebrow>

      <div style={{ marginBottom: 20 }}>
        <div style={{ fontFamily: fBody, fontSize: 12, color: C.ink500, marginBottom: 4 }}>
          Your rank
        </div>
        <div style={{ fontFamily: fMono, fontSize: 22, fontWeight: 500, color: C.ink900 }}>
          {studentRank.toLocaleString("en-IN")}
        </div>
      </div>

      <div style={{
        display: "grid", gridTemplateColumns: "1fr auto", gap: "2px 12px",
        fontFamily: fBody, fontSize: 12, color: C.ink500, marginBottom: 6, paddingBottom: 6,
        borderBottom: `1px solid ${C.line}`,
      }}>
        <span>Round</span>
        <span>Projected closing rank</span>
      </div>

      <div>
        {rounds.map((r, i) => {
          const isCrossover = i === crossoverIndex;
          return (
            <motion.div
              key={r.round}
              initial={reduceMotion ? undefined : { opacity: 0, x: -8 }}
              whileInView={reduceMotion ? undefined : { opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.3, delay: reduceMotion ? 0 : i * 0.06 }}
              style={{
                display: "grid", gridTemplateColumns: "1fr auto", alignItems: "center", gap: "2px 12px",
                padding: "10px 10px",
                marginLeft: isCrossover ? -10 : 0,
                marginRight: isCrossover ? -10 : 0,
                borderRadius: isCrossover ? 8 : 0,
                background: isCrossover ? C.signatureTint : "transparent",
                borderLeft: isCrossover ? `3px solid ${C.signature}` : "3px solid transparent",
                borderBottom: i < rounds.length - 1 ? `1px solid ${C.line}` : "none",
              }}
            >
              <div>
                <div style={{ fontFamily: fMono, fontSize: 13, color: C.ink900 }}>{`Round ${r.round}`}</div>
                {isCrossover && (
                  <div style={{ fontFamily: fBody, fontSize: 12, color: C.signature, marginTop: 2 }}>{CROSSOVER_LABEL}</div>
                )}
              </div>
              <div style={{ fontFamily: fMono, fontSize: 15, fontWeight: 500, color: isCrossover ? C.signature : C.ink700 }}>
                {r.projected_closing_rank.toLocaleString("en-IN")}
              </div>
            </motion.div>
          );
        })}
      </div>

      <p style={{ fontFamily: fBody, fontSize: 13, color: C.ink500, marginTop: 16, marginBottom: 0, lineHeight: 1.6 }}>
        {EXPECTATION_LINE}
      </p>
    </motion.div>
  );
}
