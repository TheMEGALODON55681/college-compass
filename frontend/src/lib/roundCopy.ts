import type { RoundProjectionPoint } from "./api";

// Copy for RoundProjection (docs/Design.md, docs/Rules.md section 5). Every
// string here is reviewed against the honesty rule: a round projection is
// never phrased as a promise of a seat, admission, or eligibility. "Projected
// to come within reach" describes the number, not the outcome.
//
// Timescale note (Phases.md Phase 7, Task 3): TrendBadge's supportingLine
// describes year-over-year cutoff movement across counselling seasons.
// This file describes movement within a single season's rounds, so it never
// says "year" - "season" keeps the two timescales from reading as the same
// axis when both appear on the same screen.

// The row where the projection first reaches the student's own rank
// (docs/Design.md: "the one thing this component is for"). Rank numbers run
// lower-is-better, so a round "reaches" the student once its projected
// closing rank is at or past theirs. The ratio table is not guaranteed
// monotonic (docs/BuildLog.md Phase 5), so this returns the first match, not
// the last, and -1 when the projection never reaches the student's rank.
export function findCrossoverIndex(rounds: RoundProjectionPoint[], studentRank: number): number {
  return rounds.findIndex((r) => r.projected_closing_rank >= studentRank);
}

export const CROSSOVER_LABEL = "Projected to come within reach";

export const EXPECTATION_LINE =
  "JoSAA decides each season's round count and pace, so this is a projection, not a fixed schedule.";
