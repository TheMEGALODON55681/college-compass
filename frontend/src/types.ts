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
  counsellor_available?: boolean;
  llm_endpoint_configured?: boolean;
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

export interface ApiError {
  detail: string | { msg: string; loc: (string | number)[] }[];
}
