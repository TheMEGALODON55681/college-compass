// Backend response -> UI types. band drives grouping/pill/meter color
// (mapped directly, never re-tiered from probability); admission_probability
// drives the meter number. why is synthesized client-side from real fields
// only, since the backend has no why field. See .planning/Design.md and
// .planning/phase-0-mapping.md.

import type { Band, BranchCategoryPref, CollegeResult, OwnershipPref, RecommendRequest, RecommendResponse } from "./api";
import type { College, Student, Tier } from "./types";

const BAND_TO_TIER: Record<Band, Tier> = { safe: "likely", moderate: "fair", dream: "reach" };

// A lenient profile (any branch, both ownership types, no home-state
// preference) can come back with hundreds of eligible college-branch rows
// per band - this is a shortlist, not a full eligibility dump, and
// rendering hundreds of fully-animated cards at once bogs the page down.
// Cap what renders; bandCounts() below still exposes the real totals so
// nothing is hidden, only trimmed.
const MAX_PER_BAND = 12;

export function bandCounts(response: RecommendResponse): Record<Tier, number> {
  return {
    likely: response.counts.safe,
    fair: response.counts.moderate,
    reach: response.counts.dream,
  };
}

export interface RankCardForm {
  rank: number;
  category: string; // UI label, e.g. "General"
  pwd: boolean;
  homeState: string;
  branches: string[];
  collegeTypes: string[];
}

// Design.md: translate the UI's friendly "General" label to the backend's
// "OPEN", and fold PwD into the compound category string rather than a
// separate flag - the backend has no separate PwD field.
export function translateCategory(uiCategory: string, pwd: boolean): string {
  const base = uiCategory === "General" ? "OPEN" : uiCategory;
  return pwd ? `${base} (PwD)` : base;
}

// The granular UI branch checklist has no matching backend field; the
// backend only accepts a three-way bucket. If every selected branch falls
// cleanly in one bucket, send that bucket, otherwise "any" (the honest,
// non-lossy default - see .planning/phase-0-mapping.md).
const CS_ADJACENT_BRANCHES = new Set(["Computer Science", "Information Technology", "Mathematics & Computing"]);
const CORE_BRANCHES = new Set(["Mechanical", "Electrical", "Civil", "Chemical", "Electronics & Communication"]);

export function branchesToPreference(branches: string[]): BranchCategoryPref {
  if (branches.length === 0) return "any";
  if (branches.every((b) => CS_ADJACENT_BRANCHES.has(b))) return "cs_adjacent";
  if (branches.every((b) => CORE_BRANCHES.has(b))) return "core";
  return "any";
}

// Same story for college type: the UI's four-way IIT/NIT/IIIT/GFTI picker
// has no matching request field. IIITs are the only PPP institutes; IIT,
// NIT, and GFTI are all government - a two-way split.
const PPP_TYPES = new Set(["IIIT"]);

export function collegeTypesToOwnership(collegeTypes: string[]): OwnershipPref {
  const selected = collegeTypes.filter((t) => t !== "All");
  if (selected.length === 0 || collegeTypes.includes("All")) return "both";
  if (selected.every((t) => PPP_TYPES.has(t))) return "ppp";
  if (selected.every((t) => !PPP_TYPES.has(t))) return "government";
  return "both";
}

export function buildRecommendRequest(form: RankCardForm): RecommendRequest {
  return {
    jee_rank: form.rank,
    category: translateCategory(form.category, form.pwd),
    home_state: form.homeState || null,
    preferred_branch_category: branchesToPreference(form.branches),
    institute_ownership_pref: collegeTypesToOwnership(form.collegeTypes),
  };
}

export function buildStudent(form: RankCardForm): Student {
  const year = new Date().getFullYear().toString();
  return {
    exam: "JEE Main",
    year,
    rank: form.rank,
    category: form.pwd ? `${form.category} (PwD)` : form.category,
    pwd: form.pwd,
    state: form.homeState,
    refNo: `CC-${year}-JEE-${String(form.rank).padStart(6, "0")}`,
  };
}

// The granular branch/college-type picks never hard-filter a band empty;
// they only reorder within it, so every group still shows real results.
const BRANCH_KEYWORDS: Record<string, string> = {
  "Computer Science": "computer science",
  "Electronics & Communication": "electronics",
  "Information Technology": "information technology",
  Mechanical: "mechanical",
  Electrical: "electrical",
  Civil: "civil",
  Chemical: "chemical",
  "Mathematics & Computing": "mathematics",
};

function matchesGranularPick(row: CollegeResult, form: RankCardForm): number {
  let score = 0;
  if (form.collegeTypes.length > 0 && !form.collegeTypes.includes("All") && form.collegeTypes.includes(row.institute_type)) {
    score += 1;
  }
  const wantsBranch = form.branches.some((b) => row.branch_name.toLowerCase().includes(BRANCH_KEYWORDS[b] ?? b.toLowerCase()));
  if (wantsBranch) score += 1;
  return score;
}

function quotaClause(quota: string): string {
  if (quota === "HS") return "through your home-state quota";
  if (quota === "OS") return "through the other-state quota";
  return "through the all-India quota";
}

// band and admission_probability are independent models and can disagree at
// the edges (.planning/Design.md). Reconcile that in plain words instead of
// hiding it when the gap is large enough to matter.
function reconcileClause(tier: Tier, probabilityPct: number): string {
  if (tier === "likely" && probabilityPct < 60) {
    return ` The calibrated model is a little more cautious here, at ${probabilityPct}% - worth keeping another Likely pick alongside it.`;
  }
  if (tier === "reach" && probabilityPct > 45) {
    return ` The calibrated model actually rates this more promising than the margin alone suggests, at ${probabilityPct}%.`;
  }
  return "";
}

function approximateClause(isApproximate: boolean): string {
  return isApproximate
    ? " This is an approximate estimate - there is not enough year-over-year history for this seat to be more precise."
    : "";
}

function buildWhy(row: CollegeResult, studentRank: number): string {
  const tier = BAND_TO_TIER[row.band];
  const probabilityPct = Math.round(row.admission_probability * 100);
  const rankStr = studentRank.toLocaleString("en-IN");
  const closingStr = row.predicted_closing_rank.toLocaleString("en-IN");
  const quota = quotaClause(row.quota_used);

  let lead: string;
  if (tier === "likely") {
    lead = `Your rank of ${rankStr} comfortably clears the predicted closing rank of ${closingStr}, ${quota}.`;
  } else if (tier === "fair") {
    lead = `Your rank of ${rankStr} is close to the predicted closing rank of ${closingStr}, ${quota} - realistic, and worth locking in.`;
  } else {
    lead = `Your rank of ${rankStr} is beyond the predicted closing rank of ${closingStr}, ${quota} - a genuine stretch, worth a real shot.`;
  }
  return lead + reconcileClause(tier, probabilityPct) + approximateClause(row.probability_is_approximate);
}

function toCollege(row: CollegeResult, studentRank: number): College {
  return {
    id: `${row.college_id}::${row.program_id}`,
    name: row.college_name,
    branch: row.branch_name,
    state: row.state ?? "",
    type: row.institute_type as College["type"],
    probability: Math.round(row.admission_probability * 100),
    status: BAND_TO_TIER[row.band],
    closingRank: row.predicted_closing_rank,
    why: buildWhy(row, studentRank),
  };
}

// city has no backend source at all (confirmed gap, see phase-0-mapping.md)
// - never fabricate it, just leave College.city unset.
export function formatLocation(college: Pick<College, "city" | "state">): string | null {
  const parts = [college.city, college.state].filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}

export function adaptCollegeResults(response: RecommendResponse, form: RankCardForm, studentRank: number): College[] {
  const bands: Band[] = ["safe", "moderate", "dream"];
  const colleges: College[] = [];
  for (const band of bands) {
    const rows = [...response[band]]
      .sort((a, b) => matchesGranularPick(b, form) - matchesGranularPick(a, form))
      .slice(0, MAX_PER_BAND);
    for (const row of rows) colleges.push(toCollege(row, studentRank));
  }
  return colleges;
}
