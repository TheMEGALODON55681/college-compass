export type Tier = "likely" | "fair" | "reach";

export interface College {
  id: string;
  name: string;
  branch: string;
  city?: string; // backend has no source for this - omit rather than fake it
  state: string;
  type: "IIT" | "NIT" | "IIIT" | "GFTI";
  probability: number; // 0 to 100
  status: Tier;
  closingRank: number;
  why: string; // plain, respectful, human
  // Raw ids and quota, kept alongside the composed `id` so the College
  // detail screen can call /cutoffs and /similar/{id} without parsing them
  // back out of `id`. Optional: illustrative mock cards (Landing's sample
  // preview) never navigate to a live detail fetch, so they don't set these.
  collegeId?: string;
  programId?: string;
  quotaUsed?: string;
}

export interface Student {
  name?: string;
  exam: string;
  year: string;
  rank: number;
  category: string;
  pwd?: boolean;
  state: string;
  refNo: string; // e.g. CC-2026-JEE-012480
}
