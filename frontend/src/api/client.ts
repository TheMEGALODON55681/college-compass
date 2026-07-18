import type { ApiError, ChatRequest, ChatResponse, MetaResponse, RecommendRequest, RecommendResponse, SimilarResponse } from "../types";

const API_BASE = "http://localhost:8000";

function extractErrorMessage(body: ApiError): string {
  if (typeof body.detail === "string") return body.detail;
  return body.detail.map((d) => d.msg).join("; ");
}

export async function fetchMeta(): Promise<MetaResponse> {
  const res = await fetch(`${API_BASE}/meta`);
  if (!res.ok) throw new Error("could not load form options from the server");
  return res.json();
}

export async function fetchRecommendation(request: RecommendRequest): Promise<RecommendResponse> {
  const res = await fetch(`${API_BASE}/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const body = (await res.json()) as ApiError;
    throw new Error(extractErrorMessage(body));
  }
  return res.json();
}

export async function fetchSimilarColleges(collegeId: string): Promise<SimilarResponse> {
  const res = await fetch(`${API_BASE}/similar/${encodeURIComponent(collegeId)}`);
  if (!res.ok) {
    const body = (await res.json()) as ApiError;
    throw new Error(extractErrorMessage(body));
  }
  return res.json();
}

export async function fetchReportPdf(request: RecommendRequest): Promise<Blob> {
  const res = await fetch(`${API_BASE}/report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const body = (await res.json()) as ApiError;
    throw new Error(extractErrorMessage(body));
  }
  return res.blob();
}

export async function askCounsellor(request: ChatRequest): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const body = (await res.json()) as ApiError;
    throw new Error(extractErrorMessage(body));
  }
  return res.json();
}
