// The backend is profile-based, not id-based (see .planning/Architecture.md):
// /college/:id can't be refetched cold, so the submitted profile and its
// results ride in sessionStorage. A refresh on /shortlist or /college/:id
// survives; a cold link with no session bounces to /rank-card.

import type { RecommendRequest } from "./api";
import type { College, Student, Tier } from "./types";

const KEY = "cc-session";

export interface Session {
  request: RecommendRequest;
  student: Student;
  colleges: College[];
  counts: Record<Tier, number>; // real eligible totals per tier, not just what's rendered
}

export function saveSession(session: Session): void {
  sessionStorage.setItem(KEY, JSON.stringify(session));
}

export function loadSession(): Session | null {
  const raw = sessionStorage.getItem(KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Session;
  } catch {
    return null;
  }
}
