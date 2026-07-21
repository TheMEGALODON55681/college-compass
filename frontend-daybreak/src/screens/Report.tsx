import { useState } from "react";
import { useNavigate } from "react-router";
import { motion } from "motion/react";
import { Download } from "lucide-react";
import { C, STATUS, fBody, fDisplay, fMono, shadow } from "../lib/tokens";
import type { Tier } from "../lib/types";
import { useWidth } from "../lib/useWidth";
import { Eyebrow } from "../components/Eyebrow";
import { InlineError } from "../components/states/InlineError";
import { loadSession } from "../lib/session";
import { fetchReportPdf } from "../lib/api";

// Descriptive only - the report screen never renders the PDF's own data, so
// these stay static regardless of session (Phases.md Phase 5).
const PAGES = [
  { icon: "01", title: "Student Profile", desc: "Your rank card, category, home state, and branch preferences - the full picture." },
  { icon: "02", title: "Likely Colleges", desc: "Three colleges sorted by probability with cutoff context and why-this notes." },
  { icon: "03", title: "Fair Chance Picks", desc: "Three target-range options with closing rank trends and round-by-round guidance." },
  { icon: "04", title: "Stretch Picks", desc: "Your reach options, framed as ambition with honest chance estimates." },
  { icon: "05", title: "Next Steps", desc: "JoSAA round dates, what to lock in, CSAB fallback, and state counselling to track." },
];

type DownloadState = "idle" | "loading" | "error";

export function Report() {
  const w = useWidth();
  const navigate = useNavigate();
  const mobile = w < 640;
  const session = loadSession();

  const [state, setState] = useState<DownloadState>("idle");
  const [errorMessage, setErrorMessage] = useState("");

  const handleDownload = async () => {
    if (!session) return;
    setState("loading");
    try {
      const blob = await fetchReportPdf(session.request);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `college-compass-report-${session.student.refNo}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setState("idle");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Could not generate your report. Try again in a moment.");
      setState("error");
    }
  };

  return (
    <div style={{ background: C.paper, minHeight: "100vh", padding: mobile ? "36px 16px 80px" : "52px 24px 80px" }}>
      <div style={{ maxWidth: 720, margin: "0 auto" }}>
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
          <Eyebrow>Your report</Eyebrow>
          <h1 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: "clamp(24px, 5vw, 36px)", color: C.ink900, margin: "0 0 14px", letterSpacing: "-0.01em" }}>
            College Compass Shortlist Report
          </h1>
          <p style={{ fontFamily: fBody, fontSize: 16, color: C.ink500, marginBottom: 44, lineHeight: 1.7 }}>
            A personal report for you and your family to refer to during JoSAA counselling rounds. Print it, share it, and bring it to the counsellor session.
          </p>
        </motion.div>

        {session ? (
          <motion.div
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            style={{
              background: `linear-gradient(135deg, ${C.signatureTint} 0%, ${C.primaryTint} 100%)`,
              borderRadius: 14, border: `1px solid ${C.line}`,
              padding: "22px 28px", marginBottom: 28,
              display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 14,
            }}
          >
            <div>
              <div style={{ fontFamily: fMono, fontSize: 10, color: C.primary, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>{session.student.refNo}</div>
              {session.student.name && (
                <div style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: 20, color: C.ink900 }}>{session.student.name}</div>
              )}
              <div style={{ fontFamily: fMono, fontSize: 13, color: C.ink700, marginTop: 4 }}>
                {session.student.exam} · Rank {session.student.rank.toLocaleString("en-IN")} · {session.student.category}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {(["likely", "fair", "reach"] as Tier[]).map((key) => (
                <span key={key} style={{
                  background: STATUS[key].tint, color: STATUS[key].text,
                  fontFamily: fMono, fontSize: 11, padding: "4px 12px", borderRadius: 999, letterSpacing: "0.06em",
                }}>
                  {session.counts[key]} {STATUS[key].label}
                </span>
              ))}
            </div>
          </motion.div>
        ) : (
          <motion.div
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            style={{
              background: C.surface, borderRadius: 14, border: `1px solid ${C.line}`,
              padding: "28px", marginBottom: 28,
            }}
          >
            <p style={{ fontFamily: fBody, fontSize: 16, color: C.ink700, lineHeight: 1.7, margin: "0 0 16px" }}>
              Fill in your rank card first. Your report is built from your own shortlist, so there is nothing to download yet.
            </p>
            <button onClick={() => navigate("/rank-card")} style={{
              fontFamily: fBody, fontSize: 14, fontWeight: 600, color: C.primary, background: C.primaryTint,
              border: "none", borderRadius: 10, padding: "11px 20px", cursor: "pointer", minHeight: 44,
            }}>
              Fill in your rank card
            </button>
          </motion.div>
        )}

        {/* Pages */}
        <div style={{ marginBottom: 40 }}>
          {PAGES.map((p, i) => (
            <motion.div
              key={p.icon}
              initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.2 }} transition={{ delay: i * 0.07, duration: 0.5 }}
              style={{
                background: C.surface, borderRadius: 14, border: `1px solid ${C.line}`,
                padding: "22px 26px", marginBottom: 12, boxShadow: shadow.rest,
                display: "flex", gap: 20, alignItems: "flex-start",
              }}
            >
              <div style={{ fontFamily: fMono, fontSize: 26, fontWeight: 500, color: C.primaryTint, minWidth: 44 }}>{p.icon}</div>
              <div>
                <div style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: 16, color: C.ink900, marginBottom: 5 }}>{p.title}</div>
                <div style={{ fontFamily: fBody, fontSize: 14, color: C.ink500, lineHeight: 1.65 }}>{p.desc}</div>
              </div>
            </motion.div>
          ))}
        </div>

        {session && (
          <>
            <button onClick={handleDownload} disabled={state === "loading"} style={{
              width: "100%", fontFamily: fBody, fontSize: 16, fontWeight: 600,
              color: "#fff", background: C.primary, border: "none", borderRadius: 10,
              padding: "18px", cursor: state === "loading" ? "wait" : "pointer", minHeight: 54,
              display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
            }}>
              {state === "loading" ? (
                <>
                  <span>Preparing your report</span>
                  <span style={{ display: "flex", gap: 4 }}>
                    {[0, 1, 2].map(d => (
                      <span key={d} style={{
                        width: 5, height: 5, borderRadius: "50%", background: "#fff",
                        display: "inline-block", animation: `dotBounce 1.2s ${d * 0.2}s ease-in-out infinite`,
                      }} />
                    ))}
                  </span>
                </>
              ) : (
                <>
                  <Download size={18} /> Download my report
                </>
              )}
            </button>

            {state === "error" && <InlineError message={errorMessage} />}

            <p style={{ fontFamily: fBody, fontSize: 13, color: C.ink300, textAlign: "center", marginTop: 12, marginBottom: 0 }}>
              PDF format · 5 pages · No account needed
            </p>
          </>
        )}
      </div>
    </div>
  );
}
