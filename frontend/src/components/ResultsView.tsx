import { useState } from "react";
import { fetchReportPdf, fetchSimilarColleges } from "../api/client";
import type { Band, CollegeResult, RecommendRequest, RecommendResponse, SimilarCollege } from "../types";

const BAND_LABELS: Record<Band, string> = {
  safe: "Safe",
  moderate: "Moderate",
  dream: "Dream",
};

const BAND_DESCRIPTIONS: Record<Band, string> = {
  safe: "You comfortably clear the predicted cutoff",
  moderate: "You're close to the predicted cutoff",
  dream: "A reach, but within striking distance",
};

/** The signature element: a probability meter that must never look more
 * certain than the model actually is. A confident (lag-eligible) estimate
 * fills solid; a cold-start estimate fills with a hatched texture and a
 * dashed track, on top of the "(approximate)" text - two honesty signals,
 * not one, so the distinction survives even for a user who skims past text.
 */
function ConfidenceMeter({ probability, approximate, band }: { probability: number; approximate: boolean; band: Band }) {
  const pct = Math.round(probability * 100);
  return (
    <div className={`confidence-meter confidence-${band}${approximate ? " confidence-approximate" : ""}`}>
      <div className="confidence-track" role="img" aria-label={`${pct}% admission chance${approximate ? ", approximate estimate" : ""}`}>
        <div className="confidence-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="confidence-label">
        <strong className="mono-num">{pct}%</strong> admission chance
        {approximate && (
          <span
            className="approximate-tag"
            title="This college-branch has too little year-over-year history for the main model, so this estimate leans on a wider, less certain fallback."
          >
            approximate
          </span>
        )}
      </span>
    </div>
  );
}

type SimilarStatus = "idle" | "loading" | "loaded" | "error";

function SimilarColleges({ collegeId }: { collegeId: string }) {
  const [status, setStatus] = useState<SimilarStatus>("idle");
  const [similar, setSimilar] = useState<SimilarCollege[]>([]);
  const [note, setNote] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  async function load() {
    setStatus("loading");
    try {
      const response = await fetchSimilarColleges(collegeId);
      setSimilar(response.similar);
      setNote(response.note);
      setStatus("loaded");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "could not load similar colleges");
      setStatus("error");
    }
  }

  if (status === "idle") {
    return (
      <button type="button" className="similar-colleges-toggle" onClick={load}>
        Show similar colleges
      </button>
    );
  }

  if (status === "loading") {
    return <p className="similar-colleges-loading">Loading similar colleges...</p>;
  }

  if (status === "error") {
    return (
      <p className="error-message error-message-inline" role="alert">
        {errorMessage}
      </p>
    );
  }

  return (
    <div className="similar-colleges">
      <p className="similar-colleges-note">{note}</p>
      {similar.length === 0 ? (
        <p className="similar-colleges-empty">No similar colleges on record for this one.</p>
      ) : (
        <ul className="similar-colleges-list">
          {similar.map((s) => (
            <li key={s.college_id}>
              <div className="similarity-bar-track" role="img" aria-label={`similarity score ${s.similarity_score.toFixed(2)}`}>
                <div className="similarity-bar-fill" style={{ width: `${Math.round(s.similarity_score * 100)}%` }} />
              </div>
              <div className="similar-college-text">
                <span className="similar-college-name">{s.college_name}</span>
                <span className="similar-college-meta">
                  {s.institute_type}
                  {s.state && ` · ${s.state}`}
                  {s.nirf_rank !== null && ` · NIRF #${s.nirf_rank}`}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CollegeCard({ college }: { college: CollegeResult }) {
  return (
    <div className="college-card">
      <div className="college-card-header">
        <span className="college-rank-order mono-num">#{college.rank_order}</span>
        <span className="college-name">{college.college_name}</span>
      </div>
      <div className="college-branch">{college.branch_name}</div>
      <div className="college-meta">
        <span>{college.institute_type}</span>
        {college.state && <span>{college.state}</span>}
        {college.nirf_rank !== null && (
          <span>
            NIRF <span className="mono-num">#{college.nirf_rank}</span>
          </span>
        )}
        <span>Quota: {college.quota_used}</span>
        {college.fees_annual_lakhs !== null && <span className="mono-num">{college.fees_annual_lakhs.toFixed(1)}L/yr</span>}
      </div>
      <div className="college-prediction">
        Predicted closing rank <strong className="mono-num">{college.predicted_closing_rank.toLocaleString()}</strong>
        <span className={college.margin >= 0 ? "margin-positive" : "margin-negative"}>
          {" "}
          (<span className="mono-num">
            {college.margin >= 0 ? "+" : ""}
            {college.margin.toLocaleString()}
          </span>{" "}
          margin)
        </span>
      </div>
      <ConfidenceMeter probability={college.admission_probability} approximate={college.probability_is_approximate} band={college.band} />
      <SimilarColleges collegeId={college.college_id} />
    </div>
  );
}

function BandSection({ band, colleges }: { band: Band; colleges: CollegeResult[] }) {
  if (colleges.length === 0) return null;
  return (
    <section className={`band-section band-${band}`}>
      <div className="band-heading">
        <span className="band-tab" aria-hidden="true" />
        <h2>
          {BAND_LABELS[band]} <span className="band-count mono-num">{colleges.length}</span>
        </h2>
      </div>
      <p className="band-description">{BAND_DESCRIPTIONS[band]}</p>
      <div className="college-grid">
        {colleges.map((c) => (
          <CollegeCard key={`${c.college_id}-${c.program_id}-${c.quota_used}`} college={c} />
        ))}
      </div>
    </section>
  );
}

type DownloadStatus = "idle" | "downloading" | "error";

function DownloadReportButton({ request }: { request: RecommendRequest }) {
  const [status, setStatus] = useState<DownloadStatus>("idle");
  const [errorMessage, setErrorMessage] = useState("");

  async function handleDownload() {
    setStatus("downloading");
    setErrorMessage("");
    try {
      const blob = await fetchReportPdf(request);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `college_compass_report_${request.category}_${request.jee_rank}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      setStatus("idle");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "could not generate the report");
      setStatus("error");
    }
  }

  return (
    <div className="download-report">
      <button type="button" className="download-report-button" onClick={handleDownload} disabled={status === "downloading"}>
        {status === "downloading" ? "Generating report..." : "Download report (PDF)"}
      </button>
      {status === "error" && (
        <p className="error-message error-message-inline" role="alert">
          {errorMessage}
        </p>
      )}
    </div>
  );
}

export default function ResultsView({ response, request }: { response: RecommendResponse; request: RecommendRequest }) {
  const total = response.counts.safe + response.counts.moderate + response.counts.dream;

  if (total === 0) {
    return (
      <div className="results-empty">
        No eligible colleges for this profile yet. Try a different rank, category, or fewer constraints.
      </div>
    );
  }

  return (
    <div className="results-view">
      <p className="results-summary">
        <span className="mono-num">{total}</span> eligible college-branches, based on the {response.based_on_year} forecast
        closing ranks - estimates from historical JoSAA data, not admission guarantees.
      </p>
      <DownloadReportButton request={request} />
      <BandSection band="safe" colleges={response.safe} />
      <BandSection band="moderate" colleges={response.moderate} />
      <BandSection band="dream" colleges={response.dream} />
    </div>
  );
}
