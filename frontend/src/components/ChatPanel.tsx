import { useState } from "react";
import { askCounsellor } from "../api/client";
import type { ChatResponse, RecommendRequest } from "../types";

type ChatStatus = "idle" | "asking" | "answered" | "error";

interface ChatTurn {
  question: string;
  response: ChatResponse;
}

interface ChatPanelProps {
  studentProfile: RecommendRequest | null;
}

export default function ChatPanel({ studentProfile }: ChatPanelProps) {
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [errorMessage, setErrorMessage] = useState("");

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;

    setStatus("asking");
    setErrorMessage("");
    try {
      const response = await askCounsellor({ question: trimmed, student_profile: studentProfile });
      setTurns((prev) => [...prev, { question: trimmed, response }]);
      setQuestion("");
      setStatus("answered");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "could not reach the counsellor");
      setStatus("error");
    }
  }

  return (
    <section className="chat-panel">
      <h2>
        Ask the counsellor{" "}
        <span
          className="approximate-tag"
          title={
            studentProfile
              ? "Answers use your rank, category, and preferences from the last recommendation."
              : "Run a recommendation first to personalize answers with your rank and category."
          }
        >
          {studentProfile ? "Personalized" : "General"}
        </span>
      </h2>
      <p className="chat-panel-note">
        Answers are grounded only in this system's own JoSAA data - cutoffs, forecasts, NIRF ranks, and fees. It will
        not answer placement/package questions or anything outside JEE Main / JoSAA admissions, and it will say so
        plainly if it doesn't have a figure you asked for.
      </p>

      {turns.length > 0 && (
        <div className="chat-turns" aria-live="polite">
          {turns.map((turn, i) => (
            <div key={i} className="chat-turn">
              <div className="chat-bubble chat-bubble-question">{turn.question}</div>
              <div className="chat-bubble chat-bubble-answer">
                <p>{turn.response.answer}</p>
                {turn.response.blocked_ungrounded_figure && (
                  <p className="chat-blocked-note">A figure without data backing it up was removed from this answer.</p>
                )}
                {turn.response.source_college_ids.length > 0 && (
                  <div className="chat-sources">
                    <span className="chat-sources-label">Sources</span>
                    {turn.response.source_college_ids.map((id) => (
                      <span className="chat-source-chip mono-num" key={id}>
                        {id}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {status === "error" && (
        <p className="error-message" role="alert">
          {errorMessage}
        </p>
      )}

      <form className="chat-form" onSubmit={handleAsk}>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What is the closing rank for computer science at IIT Bombay?"
          disabled={status === "asking"}
          aria-label="Ask the counsellor a question"
        />
        <button type="submit" disabled={status === "asking" || !question.trim()}>
          {status === "asking" ? "Asking..." : "Ask"}
        </button>
      </form>
    </section>
  );
}
