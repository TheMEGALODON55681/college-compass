import { useEffect, useState } from "react";
import { fetchMeta, fetchRecommendation } from "./api/client";
import StudentForm from "./components/StudentForm";
import ResultsView from "./components/ResultsView";
import ChatPanel from "./components/ChatPanel";
import type { MetaResponse, RecommendRequest, RecommendResponse } from "./types";
import "./App.css";

type Status = "loading_meta" | "meta_error" | "idle" | "submitting" | "error" | "done";

export default function App() {
  const [status, setStatus] = useState<Status>("loading_meta");
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [lastRequest, setLastRequest] = useState<RecommendRequest | null>(null);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    fetchMeta()
      .then((m) => {
        setMeta(m);
        setStatus("idle");
      })
      .catch(() => setStatus("meta_error"));
  }, []);

  async function handleSubmit(request: RecommendRequest) {
    setStatus("submitting");
    setErrorMessage("");
    try {
      const response = await fetchRecommendation(request);
      setResult(response);
      setLastRequest(request);
      setStatus("done");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "something went wrong");
      setStatus("error");
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-mark" aria-hidden="true">
          <svg viewBox="0 0 40 40" width="40" height="40">
            <circle cx="20" cy="20" r="18" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M20 8 L24 20 L20 32 L16 20 Z" fill="currentColor" opacity="0.9" />
            <circle cx="20" cy="20" r="2.5" fill="var(--paper)" />
          </svg>
        </div>
        <div>
          <h1>College Compass</h1>
          <p className="app-subtitle">
            JEE Main rank in, real JoSAA odds out - eligible colleges ranked and banded by how comfortably you clear
            each cutoff. Estimates, not guarantees.
          </p>
        </div>
      </header>

      <main className="app-main">
        {status === "loading_meta" && <p className="loading-message">Loading College Compass...</p>}
        {status === "meta_error" && (
          <p className="error-message" role="alert">
            Could not reach the backend. Is the API server running?
          </p>
        )}

        {meta && (
          <>
            <StudentForm meta={meta} submitting={status === "submitting"} onSubmit={handleSubmit} />

            {status === "error" && (
              <p className="error-message" role="alert">
                {errorMessage}
              </p>
            )}
            {status === "submitting" && <p className="loading-message">Scoring eligible colleges against real JoSAA history...</p>}
            {status === "done" && result && lastRequest && <ResultsView response={result} request={lastRequest} />}

            {meta.counsellor_available && <ChatPanel />}
          </>
        )}
      </main>
    </div>
  );
}
