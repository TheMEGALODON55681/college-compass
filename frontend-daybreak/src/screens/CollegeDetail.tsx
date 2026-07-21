import { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router";
import { motion } from "motion/react";
import { MapPin } from "lucide-react";
import { C, fBody, fDisplay, fMono, shadow } from "../lib/tokens";
import { formatLocation, quotaLabel } from "../lib/adapters";
import { loadSession } from "../lib/session";
import { useWidth } from "../lib/useWidth";
import { fetchCutoffHistory, fetchSimilarColleges } from "../lib/api";
import type { CutoffHistoryPoint, SimilarCollege } from "../lib/api";
import { Eyebrow } from "../components/Eyebrow";
import { StatusPill } from "../components/StatusPill";
import { ProbabilityMeter } from "../components/ProbabilityMeter";
import { CutoffTrendChart } from "../components/CutoffTrendChart";
import { SimilarColleges } from "../components/SimilarColleges";
import { InlineError } from "../components/states/InlineError";

type FetchState = "loading" | "ready" | "unavailable" | "error";

// No placement or salary block: the product carries no placement, package,
// or CTC data by design, permanently. That section does not exist here.
export function CollegeDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const w = useWidth();

  const session = loadSession();
  const college = session?.colleges.find(c => c.id === id);

  const [chartState, setChartState] = useState<FetchState>("loading");
  const [history, setHistory] = useState<CutoffHistoryPoint[]>([]);
  const [chartErrorMessage, setChartErrorMessage] = useState("");

  const [similarState, setSimilarState] = useState<FetchState>("loading");
  const [similar, setSimilar] = useState<SimilarCollege[]>([]);
  const [similarNote, setSimilarNote] = useState("");
  const [similarErrorMessage, setSimilarErrorMessage] = useState("");

  // Filtered to this exact result row's quota and the student's own category
  // (Phases.md): the cutoffs table holds several quota lines per
  // college-branch, and mixing them into one series would misrepresent the
  // trend this student actually faces.
  useEffect(() => {
    if (!college?.collegeId || !college.programId || !college.quotaUsed || !session) {
      setChartState("unavailable");
      return;
    }
    let cancelled = false;
    setChartState("loading");
    fetchCutoffHistory(college.collegeId, college.programId, session.request.category, college.quotaUsed)
      .then((res) => {
        if (cancelled) return;
        if (res.history.length < 2) { setChartState("unavailable"); return; }
        setHistory(res.history);
        setChartState("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setChartErrorMessage(err instanceof Error ? err.message : "Could not load cutoff history.");
        setChartState("error");
      });
    return () => { cancelled = true; };
  }, [college?.collegeId, college?.programId, college?.quotaUsed, session?.request.category]);

  useEffect(() => {
    if (!college?.collegeId) {
      setSimilarState("unavailable");
      return;
    }
    let cancelled = false;
    setSimilarState("loading");
    fetchSimilarColleges(college.collegeId)
      .then((res) => {
        if (cancelled) return;
        if (res.similar.length === 0) { setSimilarState("unavailable"); return; }
        setSimilar(res.similar);
        setSimilarNote(res.note);
        setSimilarState("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setSimilarErrorMessage(err instanceof Error ? err.message : "Could not load similar colleges.");
        setSimilarState("error");
      });
    return () => { cancelled = true; };
  }, [college?.collegeId]);

  if (!session || !college) return <Navigate to="/rank-card" replace />;

  const location = formatLocation(college);

  return (
    <div style={{ background: C.paper, minHeight: "100vh", paddingBottom: 80 }}>
      {/* Header */}
      <div style={{
        background: `linear-gradient(135deg, ${C.signatureTint} 0%, ${C.primaryTint} 100%)`,
        borderBottom: `1px solid ${C.line}`,
        padding: w < 768 ? "36px 20px 28px" : "48px 24px 36px",
      }}>
        <div style={{ maxWidth: 860, margin: "0 auto" }}>
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
              <span style={{
                fontFamily: fMono, fontSize: 10, color: C.primary, background: C.primaryTint,
                borderRadius: 6, padding: "2px 10px", letterSpacing: "0.08em", textTransform: "uppercase",
              }}>{college.type}</span>
              <StatusPill status={college.status} />
            </div>
            <h1 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: "clamp(24px, 5vw, 36px)", color: C.ink900, margin: "0 0 8px", letterSpacing: "-0.01em" }}>
              {college.name}
            </h1>
            <div style={{ fontFamily: fBody, fontSize: 18, color: C.ink700, marginBottom: 4 }}>{college.branch}</div>
            {location && (
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <MapPin size={14} color={C.ink500} />
                <span style={{ fontFamily: fBody, fontSize: 15, color: C.ink500 }}>{location}</span>
              </div>
            )}
            <div style={{ marginTop: 28, maxWidth: 480 }}>
              <div style={{ fontFamily: fMono, fontSize: 10, color: C.ink500, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>Admission probability for you</div>
              <ProbabilityMeter probability={college.probability} status={college.status} delay={300} />
            </div>
          </motion.div>
        </div>
      </div>

      <div style={{ maxWidth: 860, margin: "0 auto", padding: w < 768 ? "28px 20px" : "40px 24px" }}>
        {/* Closing rank + trend */}
        <motion.div
          initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }} transition={{ duration: 0.5 }}
          style={{ background: C.surface, borderRadius: 14, border: `1px solid ${C.line}`, padding: "28px", marginBottom: 20, boxShadow: shadow.rest }}
        >
          <Eyebrow style={{ marginBottom: 6 }}>Closing rank</Eyebrow>
          <h3 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: 18, color: C.ink900, margin: "0 0 4px" }}>
            {college.branch} · {college.name}
          </h3>
          <p style={{ fontFamily: fBody, fontSize: 13, color: C.ink500, marginBottom: 20, marginTop: 0 }}>
            Predicted for this branch and category. Lower rank is more competitive.
          </p>
          <div style={{ display: "flex", gap: 32, flexWrap: "wrap" }}>
            <div>
              <div style={{ fontFamily: fMono, fontSize: 10, color: C.ink500, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 4 }}>Your rank</div>
              <div style={{ fontFamily: fMono, fontSize: 24, fontWeight: 500, color: C.ink900 }}>{session.student.rank.toLocaleString("en-IN")}</div>
            </div>
            <div>
              <div style={{ fontFamily: fMono, fontSize: 10, color: C.ink500, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 4 }}>Predicted closing rank</div>
              <div style={{ fontFamily: fMono, fontSize: 24, fontWeight: 500, color: C.ink700 }}>{college.closingRank.toLocaleString("en-IN")}</div>
            </div>
          </div>

          <div style={{ marginTop: 24, paddingTop: 24, borderTop: `1px solid ${C.line}` }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 4 }}>
              <Eyebrow style={{ marginBottom: 0 }}>Cutoff trend</Eyebrow>
              {college.quotaUsed && (
                <span style={{ fontFamily: fMono, fontSize: 11, color: C.ink500 }}>
                  {session.student.category} · {quotaLabel(college.quotaUsed)} quota
                </span>
              )}
            </div>
            {chartState === "loading" && (
              <p style={{ fontFamily: fBody, fontSize: 13, color: C.ink500, marginTop: 12 }}>
                Reading year-over-year JoSAA data for this seat.
              </p>
            )}
            {chartState === "error" && <InlineError message={chartErrorMessage} />}
            {chartState === "unavailable" && (
              <p style={{ fontFamily: fBody, fontSize: 13, color: C.ink500, marginTop: 12, lineHeight: 1.6 }}>
                Year-over-year closing-rank history for this exact branch, category, and quota is not
                available yet. This shows only the current forecast above, not a trend.
              </p>
            )}
            {chartState === "ready" && <div style={{ marginTop: 12 }}><CutoffTrendChart history={history} /></div>}
          </div>
        </motion.div>

        {/* Why */}
        <motion.div
          initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }} transition={{ duration: 0.5, delay: 0.08 }}
          style={{ background: C.surface, borderRadius: 14, border: `1px solid ${C.line}`, padding: "28px", marginBottom: 20, boxShadow: shadow.rest }}
        >
          <Eyebrow style={{ marginBottom: 12 }}>Why this chance</Eyebrow>
          <p style={{ fontFamily: fBody, fontSize: 16, lineHeight: 1.72, color: C.ink700, margin: 0 }}>{college.why}</p>
        </motion.div>

        {/* Similar colleges */}
        {similarState !== "unavailable" && (
          <motion.div
            initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }} transition={{ duration: 0.5, delay: 0.12 }}
            style={{ background: C.surface, borderRadius: 14, border: `1px solid ${C.line}`, padding: "28px", marginBottom: 28, boxShadow: shadow.rest }}
          >
            <Eyebrow style={{ marginBottom: 12 }}>Similar colleges</Eyebrow>
            {similarState === "loading" && (
              <p style={{ fontFamily: fBody, fontSize: 13, color: C.ink500 }}>Finding colleges like this one.</p>
            )}
            {similarState === "error" && <InlineError message={similarErrorMessage} />}
            {similarState === "ready" && <SimilarColleges colleges={similar} note={similarNote} />}
          </motion.div>
        )}

        <button onClick={() => navigate("/shortlist")} style={{
          fontFamily: fBody, fontSize: 14, fontWeight: 500, color: C.primary, background: C.primaryTint,
          border: "none", borderRadius: 10, padding: "12px 24px", cursor: "pointer", minHeight: 44,
        }}>
          Back to results
        </button>
      </div>
    </div>
  );
}
