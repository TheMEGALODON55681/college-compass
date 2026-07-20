import { useState } from "react";
import { useNavigate } from "react-router";
import { motion } from "motion/react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { C, STATUS, easeOut, fBody, fDisplay, fMono, shadow } from "../lib/tokens";
import { FAQ_ITEMS, RESULTS, STUDENT } from "../lib/mockData";
import { useWidth } from "../lib/useWidth";
import { Eyebrow } from "../components/Eyebrow";
import { MiniRankCard } from "../components/MiniRankCard";
import { CollegeCard } from "../components/CollegeCard";

const STEPS = [
  { n: "01", title: "Enter your rank card", desc: "Add your JEE rank, category, home state, and the branches you care about." },
  { n: "02", title: "We rank your real options", desc: "College Compass reads five years of JoSAA seat data to estimate where students like you actually end up." },
  { n: "03", title: "Get your shortlist", desc: "A grouped list sorted by your real chances, a downloadable report, and a counsellor for anything else." },
];

export function Landing() {
  const navigate = useNavigate();
  const onStart = () => navigate("/rank-card");
  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const w = useWidth();
  const mobile = w < 768;

  return (
    <div>
      {/* Hero */}
      <section style={{
        background: `radial-gradient(ellipse 120% 70% at 70% -5%, ${C.washCool} 0%, transparent 55%),
                     radial-gradient(ellipse 70% 60% at 5% 95%, ${C.washWarm} 0%, transparent 55%),
                     ${C.paper}`,
        padding: mobile ? "60px 20px 72px" : "88px 24px 104px",
      }}>
        <div style={{
          maxWidth: 1160, margin: "0 auto",
          display: "grid",
          gridTemplateColumns: mobile ? "1fr" : "1fr 1fr",
          gap: 64, alignItems: "center",
        }}>
          <motion.div initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.56, ease: easeOut }}>
            <div style={{ fontFamily: fMono, fontSize: 11, color: C.primary, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 22 }}>
              JoSAA · 2026 · Shortlisting aid
            </div>
            <h1 style={{
              fontFamily: fDisplay, fontWeight: 600,
              fontSize: mobile ? "clamp(30px, 9vw, 44px)" : "clamp(36px, 4.5vw, 52px)",
              lineHeight: 1.08, letterSpacing: "-0.02em", color: C.ink900, marginBottom: 22,
            }}>
              Know exactly where your rank can take you.
            </h1>
            <p style={{ fontFamily: fBody, fontSize: mobile ? 16 : 18, lineHeight: 1.72, color: C.ink700, marginBottom: 38, maxWidth: 480 }}>
              College Compass reads years of real JoSAA seat data to rank the colleges you can realistically get into, sorted by your actual chances.
            </p>
            <button onClick={onStart} style={{
              fontFamily: fBody, fontSize: 16, fontWeight: 600,
              color: "#fff", background: C.primary, border: "none",
              borderRadius: 10, padding: "16px 36px", cursor: "pointer",
              minHeight: 52, animation: "breathe 3s ease-in-out infinite",
            }}>
              Find my colleges
            </button>
          </motion.div>

          {!mobile && (
            <div style={{ justifySelf: "end", width: "100%", maxWidth: 400 }}>
              <MiniRankCard />
            </div>
          )}
        </div>
      </section>

      {/* Trust strip */}
      <div style={{ background: C.primary, padding: "18px 24px" }}>
        <div style={{ maxWidth: 1160, margin: "0 auto", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: C.primaryLight, flexShrink: 0 }} />
          <p style={{ fontFamily: fBody, fontSize: 15, color: C.surface, margin: 0 }}>
            Reads real JoSAA seat-allocation data from 2020-2025, not just last year's cutoff. Every probability is based on where students like you actually ended up.
          </p>
        </div>
      </div>

      {/* How it works */}
      <section id="how" style={{ padding: mobile ? "64px 20px" : "96px 24px", background: C.paper }}>
        <div style={{ maxWidth: 1160, margin: "0 auto" }}>
          <motion.div
            initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.3 }} transition={{ duration: 0.56 }}
            style={{ marginBottom: 52 }}
          >
            <Eyebrow>How it works</Eyebrow>
            <h2 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: mobile ? "clamp(22px, 7vw, 30px)" : "clamp(26px, 3vw, 36px)", color: C.ink900, letterSpacing: "-0.01em", margin: 0 }}>
              Three steps to your shortlist.
            </h2>
          </motion.div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 24 }}>
            {STEPS.map((s, i) => (
              <motion.div
                key={s.n}
                initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, amount: 0.2 }}
                transition={{ delay: i * 0.1, duration: 0.56 }}
                style={{ background: C.surface, borderRadius: 14, padding: "28px", border: `1px solid ${C.line}`, boxShadow: shadow.rest }}
              >
                <div style={{ fontFamily: fMono, fontSize: 30, fontWeight: 500, color: C.primaryTint, marginBottom: 18 }}>{s.n}</div>
                <h3 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: 19, color: C.ink900, marginBottom: 10 }}>{s.title}</h3>
                <p style={{ fontFamily: fBody, fontSize: 15, lineHeight: 1.7, color: C.ink500, margin: 0 }}>{s.desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Sample preview */}
      <section id="preview" style={{
        background: `radial-gradient(ellipse 80% 60% at 85% 50%, ${C.washCool} 0%, transparent 65%), ${C.paper}`,
        padding: mobile ? "64px 20px" : "88px 24px",
      }}>
        <div style={{ maxWidth: 1160, margin: "0 auto" }}>
          <motion.div
            initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.2 }} transition={{ duration: 0.56 }}
            style={{ marginBottom: 48 }}
          >
            <Eyebrow>Sample shortlist</Eyebrow>
            <h2 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: mobile ? "clamp(22px, 7vw, 28px)" : "clamp(24px, 3vw, 34px)", color: C.ink900, marginBottom: 10 }}>
              Here is where your rank can genuinely take you.
            </h2>
            <p style={{ fontFamily: fBody, fontSize: 15, color: C.ink500, margin: 0 }}>
              Showing a sample for JEE Main 2026 rank 12,480 · General · Delhi.
            </p>
          </motion.div>
          <div style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
              <span style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: 18, color: C.ink900 }}>Likely</span>
              <span style={{ fontFamily: fMono, fontSize: 11, color: STATUS.likely.text, background: STATUS.likely.tint, borderRadius: 999, padding: "3px 10px" }}>3</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 16 }}>
              {RESULTS.filter(r => r.status === "likely").slice(0, 2).map((c, i) => (
                <CollegeCard key={c.id} college={c} index={i} onDetail={() => {}} studentRank={STUDENT.rank} />
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section style={{ padding: mobile ? "64px 20px" : "88px 24px", background: C.surface }}>
        <div style={{ maxWidth: 720, margin: "0 auto" }}>
          <Eyebrow>Questions</Eyebrow>
          <h2 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: mobile ? "clamp(22px, 7vw, 28px)" : 30, color: C.ink900, marginBottom: 44 }}>
            Things students ask us.
          </h2>
          {FAQ_ITEMS.map((item, i) => (
            <div key={i} style={{ borderTop: `1px solid ${C.line}` }}>
              <button
                onClick={() => setOpenFaq(openFaq === i ? null : i)}
                style={{
                  width: "100%", background: "none", border: "none", cursor: "pointer",
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "20px 0", textAlign: "left", minHeight: 64,
                }}
              >
                <span style={{ fontFamily: fBody, fontSize: 16, fontWeight: 600, color: C.ink900 }}>{item.q}</span>
                {openFaq === i ? <ChevronUp size={18} color={C.ink500} /> : <ChevronDown size={18} color={C.ink500} />}
              </button>
              {openFaq === i && (
                <div style={{ fontFamily: fBody, fontSize: 15, lineHeight: 1.72, color: C.ink500, paddingBottom: 22 }}>
                  {item.a}
                </div>
              )}
            </div>
          ))}
          <div style={{ borderTop: `1px solid ${C.line}` }} />
        </div>
      </section>

      {/* CTA banner */}
      <section style={{
        background: `linear-gradient(135deg, ${C.signatureTint} 0%, ${C.primaryTint} 100%)`,
        padding: mobile ? "64px 20px" : "88px 24px", textAlign: "center",
        borderTop: `1px solid ${C.line}`,
      }}>
        <div style={{ maxWidth: 560, margin: "0 auto" }}>
          <h2 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: mobile ? "clamp(22px, 7vw, 28px)" : 34, color: C.ink900, marginBottom: 16 }}>
            Your rank is not a verdict. Let us show you what it opens.
          </h2>
          <p style={{ fontFamily: fBody, fontSize: 16, color: C.ink500, marginBottom: 36, lineHeight: 1.7 }}>
            Enter your rank card and get a shortlist built from real JoSAA seat data.
          </p>
          <button onClick={onStart} style={{
            fontFamily: fBody, fontSize: 16, fontWeight: 600,
            color: "#fff", background: C.primary, border: "none",
            borderRadius: 10, padding: "16px 40px", cursor: "pointer", minHeight: 52,
          }}>
            Find my colleges
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer style={{ background: C.ink900, padding: "40px 24px" }}>
        <div style={{ maxWidth: 1160, margin: "0 auto", display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
          <div>
            <div style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: 16, color: "#fff", marginBottom: 6 }}>
              College<span style={{ color: C.primaryLight }}>Compass</span>
            </div>
            <p style={{ fontFamily: fBody, fontSize: 13, color: C.ink300, margin: 0, maxWidth: 360, lineHeight: 1.65 }}>
              A shortlisting aid for JEE students. Final seats depend on official JoSAA allotment.
            </p>
          </div>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <a href="#how" style={{ fontFamily: fBody, fontSize: 13, color: C.ink300, textDecoration: "none" }}>How it works</a>
            <a href="#preview" style={{ fontFamily: fBody, fontSize: 13, color: C.ink300, textDecoration: "none" }}>Colleges</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
