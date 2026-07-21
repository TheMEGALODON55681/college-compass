// Typed client for the real FastAPI backend. Root-mounted paths, no /api
// prefix - matches api/main.py exactly (see .planning/phase-0-mapping.md).
// Every call is wrapped: a network failure or a non-2xx response always
// throws a plain Error with a readable message, never an uncaught exception.

const API_BASE = import.meta.env.VITE_API_BASE || "";

export type Band = "safe" | "moderate" | "dream";
export type BranchCategoryPref = "cs_adjacent" | "core" | "any";
export type OwnershipPref = "government" | "ppp" | "both";

export interface RecommendRequest {
  jee_rank: number;
  category: string;
  home_state?: string | null;
  preferred_branch_category?: BranchCategoryPref;
  budget_annual_lakhs?: number | null;
  wants_top_nirf?: boolean;
  institute_ownership_pref?: OwnershipPref;
  prefers_home_state?: boolean;
}

export interface CollegeResult {
  rank_order: number;
  college_id: string;
  program_id: string;
  college_name: string;
  branch_name: string;
  institute_type: string;
  state: string | null;
  nirf_rank: number | null;
  band: Band;
  quota_used: string;
  predicted_closing_rank: number;
  margin: number;
  fees_annual_lakhs: number | null;
  admission_probability: number;
  probability_is_approximate: boolean;
}

export interface RecommendResponse {
  based_on_year: number;
  counts: Record<Band, number>;
  safe: CollegeResult[];
  moderate: CollegeResult[];
  dream: CollegeResult[];
}

export interface MetaResponse {
  categories: string[];
  states: string[];
  counsellor_available: boolean;
  llm_endpoint_configured: boolean;
  database_backend: string;
}

export interface ChatRequest {
  question: string;
  student_profile?: RecommendRequest | null;
}

export interface ChatResponse {
  answer: string;
  source_college_ids: string[];
  blocked_ungrounded_figure: boolean;
}

export interface SimilarCollege {
  college_id: string;
  college_name: string;
  institute_type: string;
  state: string | null;
  nirf_rank: number | null;
  similarity_score: number;
}

export interface SimilarResponse {
  college_id: string;
  similar: SimilarCollege[];
  note: string;
}

export interface CutoffHistoryPoint {
  year: number;
  closing_rank: number;
}

export interface CutoffHistoryResponse {
  college_id: string;
  program_id: string;
  category: string;
  quota: string;
  history: CutoffHistoryPoint[];
}

interface ApiErrorBody {
  detail: string | { msg: string; loc: (string | number)[] }[];
}

async function readErrorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as ApiErrorBody;
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d) => d.msg).join("; ");
  } catch {
    // response wasn't JSON - fall through to the generic message below
  }
  return `The server could not handle that (status ${res.status}). Try again in a moment.`;
}

const UNREACHABLE_MESSAGE = "Could not reach College Compass. Check your connection and try again.";

async function getJson<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`);
  } catch {
    throw new Error(UNREACHABLE_MESSAGE);
  }
  if (!res.ok) throw new Error(await readErrorMessage(res));
  return res.json();
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(UNREACHABLE_MESSAGE);
  }
  if (!res.ok) throw new Error(await readErrorMessage(res));
  return res.json();
}

export function fetchMeta(): Promise<MetaResponse> {
  return getJson<MetaResponse>("/meta");
}

export function fetchRecommendation(request: RecommendRequest): Promise<RecommendResponse> {
  return postJson<RecommendResponse>("/recommend", request);
}

export function askCounsellor(request: ChatRequest): Promise<ChatResponse> {
  return postJson<ChatResponse>("/chat", request);
}

export function fetchSimilarColleges(collegeId: string): Promise<SimilarResponse> {
  return getJson<SimilarResponse>(`/similar/${encodeURIComponent(collegeId)}`);
}

export function fetchCutoffHistory(collegeId: string, programId: string, category: string, quota: string): Promise<CutoffHistoryResponse> {
  const params = new URLSearchParams({ college_id: collegeId, program_id: programId, category, quota });
  return getJson<CutoffHistoryResponse>(`/cutoffs?${params.toString()}`);
}

export async function fetchReportPdf(request: RecommendRequest): Promise<Blob> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
  } catch {
    throw new Error(UNREACHABLE_MESSAGE);
  }
  if (!res.ok) throw new Error(await readErrorMessage(res));
  return res.blob();
}
