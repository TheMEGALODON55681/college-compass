// MOCK DATA. Results.tsx no longer uses this - it renders live sessions
// built by lib/api.ts + lib/adapters.ts. What remains here is genuinely
// static: the Landing page's illustrative sample shortlist (PRD.md scopes
// Landing as "static, no backend data"), the FAQ copy, and mock content for
// screens not yet wired (CollegeDetail's cutoff chart is Phase 3, the
// Counsellor reply is Phase 4).

import type { College, Student, Tier } from "./types";

export const STUDENT: Student = {
  name: "Arjun Mehta",
  exam: "JEE Main",
  year: "2026",
  rank: 12480,
  category: "General",
  state: "Delhi",
  refNo: "CC-2026-JEE-012480",
};

export const RESULTS: College[] = [
  {
    id: "1", name: "NIT Delhi", branch: "Electronics & Communication", city: "Delhi", state: "Delhi",
    type: "NIT", probability: 90, status: "likely", closingRank: 13840,
    why: "Students with your rank and General category from Delhi consistently land this seat through home-state quota. Strong historical pattern across five rounds.",
  },
  {
    id: "2", name: "NIT Kurukshetra", branch: "Computer Engineering", city: "Kurukshetra", state: "Haryana",
    type: "NIT", probability: 88, status: "likely", closingRank: 14210,
    why: "Consistent closing over the last four years - your rank sits comfortably within the range, even without home-state advantage.",
  },
  {
    id: "3", name: "NIT Jalandhar", branch: "Information Technology", city: "Jalandhar", state: "Punjab",
    type: "NIT", probability: 85, status: "likely", closingRank: 13980,
    why: "This branch expanded seats in recent years, opening the range to your rank reliably across most JoSAA rounds.",
  },
  {
    id: "4", name: "NIT Warangal", branch: "Electrical Engineering", city: "Warangal", state: "Telangana",
    type: "NIT", probability: 60, status: "fair", closingRank: 12640,
    why: "Competitive but realistic - about half of students in your position have landed this seat in later rounds. Worth locking in.",
  },
  {
    id: "5", name: "NIT Delhi", branch: "Computer Science", city: "Delhi", state: "Delhi",
    type: "NIT", probability: 58, status: "fair", closingRank: 11890,
    why: "CSE at NIT Delhi is high demand, but later rounds often open a few seats. Your rank is close enough to be in the running.",
  },
  {
    id: "6", name: "NIT Surathkal", branch: "Information Technology", city: "Surathkal", state: "Karnataka",
    type: "NIT", probability: 55, status: "fair", closingRank: 12120,
    why: "Rounds 4 and 5 have historically seen movement here. Worth including in your shortlist alongside your Likely picks.",
  },
  {
    id: "7", name: "NIT Warangal", branch: "Computer Science", city: "Warangal", state: "Telangana",
    type: "NIT", probability: 28, status: "reach", closingRank: 11240,
    why: "A genuine stretch - NIT Warangal CSE sometimes surprises in later rounds. Worth one of your locked choices as an ambitious pick.",
  },
  {
    id: "8", name: "NIT Trichy", branch: "Computer Science", city: "Tiruchirappalli", state: "Tamil Nadu",
    type: "NIT", probability: 25, status: "reach", closingRank: 10980,
    why: "NIT Trichy CSE is among the most competitive in the country. Your rank has a real, if slim, chance - and it costs nothing to lock it in.",
  },
];

export const FAQ_ITEMS = [
  { q: "How accurate is this?", a: "College Compass reads five years of real JoSAA seat-allocation data to estimate where students like you actually end up - not just last year's cutoff. Probabilities are estimates based on historical patterns, not guarantees." },
  { q: "What data does it use?", a: "Official JoSAA opening and closing ranks from 2020 to 2025, across all rounds, for every college and category. Data comes directly from the JoSAA portal." },
  { q: "Is it free?", a: "Yes, completely free. The shortlist, the report, and the counsellor are all included." },
  { q: "What about home-state quota?", a: "Yes, home-state quota is factored in. When you enter your state, we adjust probabilities for the seats reserved for home-state candidates." },
  { q: "What if my rank is lower than I hoped?", a: "Enter it honestly. The shortlist will lead with the colleges you can realistically get, including options you might not have considered. Many students find strong matches they had overlooked." },
  { q: "Is this the final allotment?", a: "No. This is a shortlisting aid. Official seats are allocated by JoSAA after you submit your choices. Final results depend on the official allotment process." },
];

export const MINI_RANK_CARD_FIELDS = [
  { label: "Exam", value: "JEE Main 2026" },
  { label: "CRL Rank", value: "12,480" },
  { label: "Category", value: "General" },
  { label: "Home State", value: "Delhi" },
];

export const MINI_RANK_CARD_DEMOS: { name: string; branch: string; prob: number; status: Tier }[] = [
  { name: "NIT Delhi", branch: "Electronics & Communication", prob: 90, status: "likely" },
  { name: "NIT Delhi", branch: "Computer Science", prob: 58, status: "fair" },
  { name: "NIT Warangal", branch: "Computer Science", prob: 28, status: "reach" },
];
