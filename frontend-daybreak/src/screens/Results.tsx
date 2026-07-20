import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router";
import { motion } from "motion/react";
import { Download, MessageCircle } from "lucide-react";
import { C, STATUS, fBody, fMono } from "../lib/tokens";
import type { Tier } from "../lib/types";
import { loadSession } from "../lib/session";
import { useWidth } from "../lib/useWidth";
import { ResultGroup } from "../components/ResultGroup";
import { CareStateBlock } from "../components/CareStateBlock";
import { EmptyState } from "../components/states/EmptyState";

export function Results() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Tier | "all">("all");
  const [banner, setBanner] = useState(true);
  const [previewCare, setPreviewCare] = useState(false);
  const w = useWidth();
  const mobile = w < 768;

  useEffect(() => { const t = setTimeout(() => setBanner(false), 4000); return () => clearTimeout(t); }, []);

  const session = loadSession();
  if (!session) return <Navigate to="/rank-card" replace />;
  const { colleges, student, counts } = session;

  if (colleges.length === 0) {
    return (
      <div style={{ background: C.paper, minHeight: "100vh", padding: mobile ? "28px 16px 100px" : "36px 24px 80px" }}>
        <EmptyState onAdjust={() => navigate("/rank-card")} />
      </div>
    );
  }

  const likely = previewCare ? [] : colleges.filter(r => r.status === "likely");
  const fair = colleges.filter(r => r.status === "fair");
  const reach = colleges.filter(r => r.status === "reach");
  const showingCare = likely.length === 0;
  const likelyTotal = previewCare ? 0 : counts.likely;

  return (
    <div style={{ background: C.paper, minHeight: "100vh" }}>
      {banner && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          style={{
            background: `linear-gradient(135deg, ${C.signatureTint}, ${C.primaryTint})`,
            borderBottom: `1px solid ${C.line}`, padding: "14px 24px", textAlign: "center",
          }}
        >
          <p style={{ fontFamily: fBody, fontSize: 16, color: C.ink700, margin: 0 }}>
            {showingCare
              ? "You have real options here. Let us start with your strongest ones."
              : "Here is where your rank can genuinely take you."
            }
          </p>
        </motion.div>
      )}

      {/* Results header */}
      <div style={{ background: C.surface, borderBottom: `1px solid ${C.line}`, padding: "32px 24px" }}>
        <div style={{ maxWidth: 1160, margin: "0 auto" }}>
          <div style={{
            background: C.paper, borderRadius: 10, border: `1px solid ${C.line}`,
            padding: "14px 20px", marginBottom: 24,
            display: "flex", flexWrap: "wrap", gap: mobile ? 16 : 32,
          }}>
            {[
              { label: "Exam", value: student.exam },
              { label: "CRL Rank", value: student.rank.toLocaleString("en-IN") },
              { label: "Category", value: student.category },
              { label: "Home State", value: student.state || "Not specified" },
              { label: "Ref", value: student.refNo },
            ].map(f => (
              <div key={f.label}>
                <div style={{ fontFamily: fMono, fontSize: 10, color: C.ink500, letterSpacing: "0.08em", textTransform: "uppercase" }}>{f.label}</div>
                <div style={{ fontFamily: fMono, fontSize: 13, fontWeight: 500, color: C.ink900 }}>{f.value}</div>
              </div>
            ))}
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16 }}>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {(["likely", "fair", "reach"] as Tier[]).map(key => (
                <div key={key} style={{
                  background: STATUS[key].tint, borderRadius: 10, padding: "10px 16px",
                  textAlign: "center", minWidth: 80,
                }}>
                  <div style={{ fontFamily: fMono, fontSize: 22, fontWeight: 500, color: STATUS[key].text }}>
                    {key === "likely" ? likelyTotal : key === "fair" ? counts.fair : counts.reach}
                  </div>
                  <div style={{ fontFamily: fMono, fontSize: 10, color: STATUS[key].solid, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                    {STATUS[key].label}
                  </div>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button onClick={() => navigate("/counsellor")} style={{
                fontFamily: fBody, fontSize: 14, fontWeight: 500, color: C.primary, background: C.primaryTint,
                border: "none", borderRadius: 10, padding: "10px 18px", cursor: "pointer",
                display: "flex", alignItems: "center", gap: 6, minHeight: 44,
              }}>
                <MessageCircle size={16} /> Ask counsellor
              </button>
              {!mobile && (
                <button onClick={() => navigate("/report")} style={{
                  fontFamily: fBody, fontSize: 14, fontWeight: 500, color: C.ink700, background: C.paper,
                  border: `1px solid ${C.line}`, borderRadius: 10, padding: "10px 18px", cursor: "pointer",
                  display: "flex", alignItems: "center", gap: 6, minHeight: 44,
                }}>
                  <Download size={16} /> Download report
                </button>
              )}
              <button onClick={() => setPreviewCare(!previewCare)} style={{
                fontFamily: fMono, fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase",
                color: previewCare ? C.signature : C.ink300, background: "transparent",
                border: `1px solid ${previewCare ? C.signature : C.line}`,
                borderRadius: 8, padding: "6px 12px", cursor: "pointer", minHeight: 44,
              }}>
                {previewCare ? "Exit care state" : "Preview care state"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Filter bar */}
      <div style={{
        position: "sticky", top: 64, zIndex: 50,
        background: "rgba(251,250,246,0.95)", backdropFilter: "blur(10px)",
        borderBottom: `1px solid ${C.line}`, padding: "10px 24px",
      }}>
        <div style={{ maxWidth: 1160, margin: "0 auto", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontFamily: fMono, fontSize: 10, color: C.ink300, letterSpacing: "0.08em", textTransform: "uppercase", marginRight: 4 }}>Filter:</span>
          {(["all", "likely", "fair", "reach"] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)} style={{
              fontFamily: fBody, fontSize: 13, fontWeight: 500,
              color: filter === f ? C.primary : C.ink500,
              background: filter === f ? C.primaryTint : "transparent",
              border: `1px solid ${filter === f ? C.primary : C.line}`,
              borderRadius: 8, padding: "6px 14px", cursor: "pointer", minHeight: 44,
              textTransform: f === "all" ? "none" : "capitalize",
            }}>
              {f === "all" ? "All" : STATUS[f].label}
            </button>
          ))}
        </div>
      </div>

      {/* Result groups */}
      <div style={{ maxWidth: 1160, margin: "0 auto", padding: mobile ? "28px 16px 100px" : "36px 24px 80px" }}>
        {showingCare && <CareStateBlock onCounsellor={() => navigate("/counsellor")} />}
        {(filter === "all" || filter === "likely") && (
          <ResultGroup
            title="Likely" subtitle="Colleges you can realistically count on"
            count={likelyTotal} colleges={likely}
            onDetail={(c) => navigate(`/college/${encodeURIComponent(c.id)}`)}
            baseIndex={0} studentRank={student.rank}
          />
        )}
        {(filter === "all" || filter === "fair") && (
          <ResultGroup
            title="Fair chance" subtitle="Worth making these your main targets"
            count={counts.fair} colleges={fair}
            onDetail={(c) => navigate(`/college/${encodeURIComponent(c.id)}`)}
            baseIndex={likely.length} studentRank={student.rank}
          />
        )}
        {(filter === "all" || filter === "reach") && (
          <ResultGroup
            title="Your stretch picks" subtitle="Worth a real shot - ambition locked in here"
            count={counts.reach} colleges={reach}
            onDetail={(c) => navigate(`/college/${encodeURIComponent(c.id)}`)}
            baseIndex={likely.length + fair.length} studentRank={student.rank}
          />
        )}
      </div>

      {/* Mobile bottom bar */}
      {mobile && (
        <div style={{
          position: "fixed", bottom: 0, left: 0, right: 0,
          background: C.surface, borderTop: `1px solid ${C.line}`, padding: "12px 20px",
        }}>
          <button onClick={() => navigate("/report")} style={{
            width: "100%", fontFamily: fBody, fontSize: 15, fontWeight: 600,
            color: "#fff", background: C.primary, border: "none", borderRadius: 10,
            padding: "15px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
          }}>
            <Download size={18} /> Download report
          </button>
        </div>
      )}
    </div>
  );
}
