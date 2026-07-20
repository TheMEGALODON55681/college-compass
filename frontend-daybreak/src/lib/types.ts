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
