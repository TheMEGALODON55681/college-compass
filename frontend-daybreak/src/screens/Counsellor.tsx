import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { BookOpen, Send } from "lucide-react";
import { C, fBody, fDisplay, fMono, shadow } from "../lib/tokens";
import { Eyebrow } from "../components/Eyebrow";
import { InlineError } from "../components/states/InlineError";
import { askCounsellor } from "../lib/api";
import { loadSession } from "../lib/session";
import { collegeNameFromId } from "../lib/adapters";

interface ChatMsg {
  role: "student" | "counsellor" | "error";
  text: string;
  sources?: string[];
  blocked?: boolean;
}

// Named colleges and topics chosen so each one actually hits the grounded
// counsellor's structured lookup, not placement or salary (which it refuses).
const STARTERS = [
  "What is the closing rank for CSE at NIT Warangal?",
  "What branches are available at IIT Bombay?",
  "Explain the JoSAA rounds.",
  "How does home-state quota work at NITs?",
];

// The LLM sometimes answers in markdown; this is a plain-text bubble, not a
// markdown renderer, so strip the bold marker rather than show it literally.
function stripBoldMarkers(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, "$1");
}

export function Counsellor() {
  const session = loadSession();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || typing) return;
    setMessages((prev) => [...prev, { role: "student", text: question }]);
    setInput("");
    setTyping(true);
    try {
      const res = await askCounsellor({ question, student_profile: session?.request ?? null });
      const sources = [...new Set(res.source_college_ids)].map((id) => collegeNameFromId(id, session?.colleges));
      setMessages((prev) => [...prev, { role: "counsellor", text: stripBoldMarkers(res.answer), sources, blocked: res.blocked_ungrounded_figure }]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: "error", text: err instanceof Error ? err.message : "Something went wrong. Try asking again." }]);
    } finally {
      setTyping(false);
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, typing]);

  return (
    <div style={{ background: C.paper, minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div style={{ background: C.surface, borderBottom: `1px solid ${C.line}`, padding: "22px 24px" }}>
        <div style={{ maxWidth: 720, margin: "0 auto" }}>
          <Eyebrow style={{ marginBottom: 4 }}>Counsellor</Eyebrow>
          <h2 style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: 22, color: C.ink900, margin: "0 0 4px" }}>Ask about cutoffs and counselling</h2>
          <p style={{ fontFamily: fBody, fontSize: 14, color: C.ink500, margin: 0 }}>
            {session
              ? "Answers grounded in real JoSAA seat data, personalized to your rank card."
              : "Answers grounded in real JoSAA seat data."}
          </p>
        </div>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
        <div style={{ maxWidth: 720, margin: "0 auto" }}>
          {messages.length === 0 && (
            <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
              <div style={{
                background: C.surface, borderRadius: 14, border: `1px solid ${C.line}`,
                padding: "36px 28px", textAlign: "center", marginBottom: 32,
              }}>
                <div style={{ fontFamily: fDisplay, fontSize: 20, fontWeight: 600, color: C.ink900, marginBottom: 8 }}>
                  What would you like to know?
                </div>
                <p style={{ fontFamily: fBody, fontSize: 15, color: C.ink500, margin: 0 }}>
                  Ask about cutoffs, branches, rounds, or anything about your shortlist.
                </p>
              </div>
              <div style={{ fontFamily: fMono, fontSize: 10, color: C.ink300, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>Try asking</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 32 }}>
                {STARTERS.map(q => (
                  <button key={q} onClick={() => send(q)} disabled={typing} style={{
                    fontFamily: fBody, fontSize: 13, color: C.primary, background: C.primaryTint,
                    border: `1px solid ${C.primaryTint}`, borderRadius: 8, padding: "9px 14px",
                    cursor: typing ? "not-allowed" : "pointer", textAlign: "left", minHeight: 44,
                  }}>{q}</button>
                ))}
              </div>
            </motion.div>
          )}

          {messages.map((m, i) => {
            if (m.role === "error") {
              return (
                <motion.div key={i} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }} style={{ marginBottom: 16 }}>
                  <InlineError message={m.text} />
                </motion.div>
              );
            }
            return (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35 }}
                style={{
                  marginBottom: 16, display: "flex",
                  flexDirection: m.role === "student" ? "row-reverse" : "row",
                  gap: 10, alignItems: "flex-end",
                }}
              >
                {m.role === "counsellor" && (
                  <div style={{
                    width: 32, height: 32, borderRadius: "50%", background: C.primaryTint,
                    display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                  }}>
                    <BookOpen size={14} color={C.primary} />
                  </div>
                )}
                <div style={{
                  maxWidth: "75%",
                  background: m.role === "student" ? C.primary : C.surface,
                  color: m.role === "student" ? "#fff" : C.ink700,
                  borderRadius: m.role === "student" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
                  padding: "12px 16px",
                  border: m.role === "counsellor" ? `1px solid ${C.line}` : "none",
                  boxShadow: m.role === "counsellor" ? shadow.rest : "none",
                }}>
                  <p style={{ fontFamily: fBody, fontSize: 15, lineHeight: 1.65, margin: 0, whiteSpace: "pre-wrap" }}>{m.text}</p>
                  {m.blocked && (
                    <p style={{ fontFamily: fBody, fontSize: 12, color: C.ink500, margin: "10px 0 0", lineHeight: 1.5 }}>
                      A figure in this answer could not be verified against real data, so it was left out.
                    </p>
                  )}
                  {m.sources && m.sources.length > 0 && (
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
                      {m.sources.map(s => (
                        <span key={s} style={{
                          fontFamily: fMono, fontSize: 10, color: C.ink500,
                          background: C.paper, border: `1px solid ${C.line}`,
                          borderRadius: 4, padding: "2px 6px", letterSpacing: "0.04em",
                        }}>{s}</span>
                      ))}
                    </div>
                  )}
                </div>
              </motion.div>
            );
          })}

          {typing && (
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              style={{ display: "flex", gap: 10, alignItems: "flex-end", marginBottom: 16 }}
            >
              <div style={{ width: 32, height: 32, borderRadius: "50%", background: C.primaryTint, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <BookOpen size={14} color={C.primary} />
              </div>
              <div style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: "14px 14px 14px 4px", padding: "14px 18px", display: "flex", gap: 5 }}>
                {[0, 1, 2].map(d => (
                  <div key={d} style={{ width: 6, height: 6, borderRadius: "50%", background: C.ink300, animation: `dotBounce 1.2s ${d * 0.2}s ease-in-out infinite` }} />
                ))}
              </div>
            </motion.div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Composer */}
      <div style={{ background: C.surface, borderTop: `1px solid ${C.line}`, padding: "14px 24px" }}>
        <div style={{ maxWidth: 720, margin: "0 auto", display: "flex", gap: 10 }}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && send(input)}
            disabled={typing}
            placeholder="Ask about cutoffs, branches, or counselling rounds."
            style={{
              flex: 1, fontFamily: fBody, fontSize: 15, color: C.ink900,
              background: C.paper, border: `1px solid ${C.line}`,
              borderRadius: 10, padding: "13px 16px", outline: "none", minHeight: 50,
            }}
            onFocus={e => e.target.style.borderColor = C.primary}
            onBlur={e => e.target.style.borderColor = C.line}
          />
          <button onClick={() => send(input)} disabled={!input.trim() || typing} style={{
            background: input.trim() && !typing ? C.primary : C.paper,
            border: `1px solid ${input.trim() && !typing ? C.primary : C.line}`,
            borderRadius: 10, padding: "0 18px", cursor: input.trim() && !typing ? "pointer" : "not-allowed",
            display: "flex", alignItems: "center", justifyContent: "center", minWidth: 50, minHeight: 50,
            transition: "all 160ms",
          }}>
            <Send size={18} color={input.trim() && !typing ? "#fff" : C.ink300} />
          </button>
        </div>
      </div>
    </div>
  );
}
