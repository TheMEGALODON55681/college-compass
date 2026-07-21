import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { useNavigate } from "react-router";
import { motion } from "motion/react";
import { C, easeOut, fBody, fDisplay, fMono, shadow } from "../lib/tokens";
import { useWidth } from "../lib/useWidth";
import { fetchMeta, fetchRecommendation } from "../lib/api";
import { adaptCollegeResults, bandCounts, buildRecommendRequest, buildStudent } from "../lib/adapters";
import { saveSession } from "../lib/session";
import { InlineError } from "../components/states/InlineError";

const BRANCHES = ["Computer Science", "Electronics & Communication", "Information Technology", "Mechanical", "Electrical", "Civil", "Chemical", "Mathematics & Computing"];
const COLLEGE_TYPES = ["IIT", "NIT", "IIIT", "GFTI", "All"];
const CATEGORIES = ["General", "EWS", "OBC-NCL", "SC", "ST"];
const FALLBACK_STATES = ["Andhra Pradesh", "Bihar", "Delhi", "Gujarat", "Haryana", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Punjab", "Rajasthan", "Tamil Nadu", "Telangana", "Uttar Pradesh", "West Bengal"];

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 22 }}>
      <div style={{ fontFamily: fMono, fontSize: 10, color: C.ink500, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>{label}</div>
      {children}
    </div>
  );
}

export function RankCard() {
  const navigate = useNavigate();
  const [rank, setRank] = useState("");
  const [category, setCategory] = useState("General");
  const [pwd, setPwd] = useState(false);
  const [homeState, setHomeState] = useState("");
  const [branches, setBranches] = useState<string[]>([]);
  const [collegeTypes, setCollegeTypes] = useState<string[]>([]);
  const [states, setStates] = useState<string[]>(FALLBACK_STATES);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const w = useWidth();
  const mobile = w < 640;

  useEffect(() => {
    fetchMeta().then((m) => { if (m.states.length > 0) setStates(m.states); }).catch(() => {});
  }, []);

  const toggle = (arr: string[], val: string, set: (a: string[]) => void) =>
    set(arr.includes(val) ? arr.filter(x => x !== val) : [...arr, val]);

  const submit = async () => {
    const parsedRank = Number(rank);
    if (!rank.trim() || !Number.isInteger(parsedRank) || parsedRank < 1 || parsedRank > 2_000_000) {
      setError("That rank looks off. Enter your JEE Main rank as a whole number, 1 to 2,000,000.");
      return;
    }
    setError(null);
    setLoading(true);
    const form = { rank: parsedRank, category, pwd, homeState, branches, collegeTypes };
    try {
      const request = buildRecommendRequest(form);
      const response = await fetchRecommendation(request);
      const colleges = adaptCollegeResults(response, form, parsedRank);
      const student = buildStudent(form);
      saveSession({ request, student, colleges, counts: bandCounts(response) });
      navigate("/shortlist");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Try again.");
      setLoading(false);
    }
  };

  const inputStyle: CSSProperties = {
    width: "100%", fontFamily: fMono, fontSize: 15,
    color: C.ink900, background: C.paper,
    border: `1px solid ${C.line}`, borderRadius: 10,
    padding: "12px 16px", boxSizing: "border-box", outline: "none",
  };

  const selectStyle: CSSProperties = {
    ...inputStyle, fontFamily: fBody, fontSize: 14, cursor: "pointer", appearance: "none",
  };

  return (
    <div style={{ background: C.paper, minHeight: "100vh", padding: mobile ? "32px 16px 80px" : "48px 24px 80px" }}>
      <div style={{ maxWidth: 680, margin: "0 auto" }}>
        <motion.div
          initial={{ opacity: 0, y: 28 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.56, ease: easeOut }}
          style={{ background: C.surface, borderRadius: 14, border: `1px solid ${C.line}`, boxShadow: shadow.signature, overflow: "hidden" }}
        >
          {/* Card header */}
          <div style={{
            background: `linear-gradient(135deg, ${C.signatureTint} 0%, ${C.primaryTint} 100%)`,
            padding: "28px 32px 24px", borderBottom: `1px solid ${C.line}`,
            display: "flex", justifyContent: "space-between", alignItems: "flex-start",
          }}>
            <div>
              <div style={{ fontFamily: fMono, fontSize: 10, color: C.primary, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>
                College Compass · Rank Card Input
              </div>
              <h1 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: 26, color: C.ink900, margin: 0, letterSpacing: "-0.01em" }}>Your rank card</h1>
              <p style={{ fontFamily: fBody, fontSize: 14, color: C.ink500, margin: "6px 0 0" }}>Fill in your details and we will build your shortlist.</p>
            </div>
            <div style={{ fontFamily: fMono, fontSize: 9, color: C.ink300, textAlign: "right", lineHeight: 1.5 }}>REF: CC-2026<br />JEE-XXXXXX</div>
          </div>

          <div style={{ padding: mobile ? "24px 20px" : "32px 32px" }}>
            {/* Rank */}
            <Field label="CRL rank">
              <input
                type="text" inputMode="numeric" value={rank}
                onChange={e => setRank(e.target.value)}
                placeholder="Enter your CRL rank, e.g. 12480"
                style={inputStyle}
                onFocus={e => e.target.style.borderColor = C.primary}
                onBlur={e => e.target.style.borderColor = C.line}
              />
            </Field>

            <Field label="Category">
              <select value={category} onChange={e => setCategory(e.target.value)} style={selectStyle}>
                {CATEGORIES.map(c => <option key={c}>{c}</option>)}
              </select>
            </Field>

            <Field label="PwD status">
              <button onClick={() => setPwd(!pwd)} style={{
                fontFamily: fBody, fontSize: 14,
                color: pwd ? C.primary : C.ink500,
                background: pwd ? C.primaryTint : C.paper,
                border: `1px solid ${pwd ? C.primary : C.line}`,
                borderRadius: 10, padding: "10px 20px", cursor: "pointer", minHeight: 44,
                transition: "all 160ms cubic-bezier(0.34, 1.4, 0.64, 1)",
              }}>
                {pwd ? "PwD - yes" : "PwD - no"}
              </button>
            </Field>

            <p style={{ fontFamily: fBody, fontSize: 13, color: C.ink500, lineHeight: 1.6, marginTop: -8, marginBottom: 22 }}>
              This tool estimates Gender-Neutral pool seats only. Female-only supernumerary seats are not modeled here.
            </p>

            <Field label="Home state">
              <select value={homeState} onChange={e => setHomeState(e.target.value)} style={selectStyle}>
                <option value="">Not specified</option>
                {states.map(s => <option key={s}>{s}</option>)}
              </select>
            </Field>

            <Field label="Preferred branches">
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {BRANCHES.map(b => (
                  <button key={b} onClick={() => toggle(branches, b, setBranches)} style={{
                    fontFamily: fBody, fontSize: 13,
                    color: branches.includes(b) ? C.primary : C.ink500,
                    background: branches.includes(b) ? C.primaryTint : C.paper,
                    border: `1px solid ${branches.includes(b) ? C.primary : C.line}`,
                    borderRadius: 8, padding: "8px 14px", cursor: "pointer", minHeight: 44,
                    transition: "all 160ms cubic-bezier(0.34, 1.4, 0.64, 1)",
                  }}>{b}</button>
                ))}
              </div>
            </Field>

            <Field label="College type">
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {COLLEGE_TYPES.map(t => (
                  <button key={t} onClick={() => toggle(collegeTypes, t, setCollegeTypes)} style={{
                    fontFamily: fMono, fontSize: 12, letterSpacing: "0.06em", textTransform: "uppercase",
                    color: collegeTypes.includes(t) ? C.primary : C.ink500,
                    background: collegeTypes.includes(t) ? C.primaryTint : C.paper,
                    border: `1px solid ${collegeTypes.includes(t) ? C.primary : C.line}`,
                    borderRadius: 8, padding: "8px 14px", cursor: "pointer", minHeight: 44,
                  }}>{t}</button>
                ))}
              </div>
            </Field>

            <button onClick={submit} disabled={loading} style={{
              width: "100%", fontFamily: fBody, fontSize: 16, fontWeight: 600,
              color: "#fff", background: loading ? C.ink300 : C.primary,
              border: "none", borderRadius: 10, padding: "16px",
              cursor: loading ? "not-allowed" : "pointer", marginTop: 8, minHeight: 54,
              transition: "background 200ms",
            }}>
              {loading ? "Building your shortlist…" : "Show my matches"}
            </button>

            {loading && (
              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                style={{ fontFamily: fBody, fontSize: 13, color: C.ink500, textAlign: "center", marginTop: 12 }}
              >
                Reading five years of JoSAA seat data for you.
              </motion.p>
            )}

            {error && <InlineError message={error} />}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
