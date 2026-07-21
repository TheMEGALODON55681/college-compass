import { C, fBody, fDisplay, fMono, shadow } from "../lib/tokens";
import type { SimilarCollege } from "../lib/api";

// Item-to-item, not personalized to this student (see SimilarResponse.note) -
// informational only, so these cards don't link into /college/:id: there is
// no session-consistent probability or branch to show for a college outside
// the student's own results.
export function SimilarColleges({ colleges, note }: { colleges: SimilarCollege[]; note: string }) {
  return (
    <div>
      <div style={{ display: "flex", gap: 14, overflowX: "auto", paddingBottom: 6 }}>
        {colleges.map((c) => (
          <div key={c.college_id} style={{
            minWidth: 210, flexShrink: 0, background: C.surface, border: `1px solid ${C.line}`,
            borderRadius: 14, padding: "16px 18px", boxShadow: shadow.rest,
          }}>
            <span style={{
              fontFamily: fMono, fontSize: 10, color: C.primary, background: C.primaryTint,
              borderRadius: 6, padding: "2px 8px", letterSpacing: "0.08em", textTransform: "uppercase",
            }}>{c.institute_type}</span>
            <div style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: 15, color: C.ink900, margin: "8px 0 4px" }}>
              {c.college_name}
            </div>
            <div style={{ fontFamily: fBody, fontSize: 13, color: C.ink500 }}>
              {[c.state, c.nirf_rank ? `NIRF #${c.nirf_rank}` : null].filter(Boolean).join(" · ") || "Location not on record"}
            </div>
          </div>
        ))}
      </div>
      <p style={{ fontFamily: fBody, fontSize: 12, color: C.ink500, marginTop: 10, marginBottom: 0 }}>{note}</p>
    </div>
  );
}
