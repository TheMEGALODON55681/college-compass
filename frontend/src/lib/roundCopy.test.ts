// Runnable check for roundCopy.ts, same pattern as trendCopy.test.ts: plain
// assertions, no test framework, run with `node src/lib/roundCopy.test.ts`.

import type { RoundProjectionPoint } from "./api.ts";
import { findCrossoverIndex } from "./roundCopy.ts";

function check(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

function rounds(ranks: number[]): RoundProjectionPoint[] {
  return ranks.map((projected_closing_rank, i) => ({ round: i + 1, projected_closing_rank }));
}

// Mid-table crossover: rounds 1-3 stay tighter than the student's rank,
// round 4 reaches it.
{
  const i = findCrossoverIndex(rounds([500, 700, 900, 1300, 1500, 1600]), 1200);
  check(i === 3, `expected index 3 (round 4), got ${i}`);
}

// Clears round 1 already: the very first row is the crossover.
{
  const i = findCrossoverIndex(rounds([1500, 1600, 1700, 1800, 1900, 2000]), 1200);
  check(i === 0, `expected index 0 (round 1), got ${i}`);
}

// Never clears any round: no row is the crossover.
{
  const i = findCrossoverIndex(rounds([100, 200, 300, 400, 500, 600]), 5000);
  check(i === -1, `expected -1 (no crossover), got ${i}`);
}

// Exact equality counts as a crossover, not just strictly past it.
{
  const i = findCrossoverIndex(rounds([800, 1000, 1200, 1400, 1600, 1800]), 1200);
  check(i === 2, `expected index 2 (exact match at round 3), got ${i}`);
}

// Non-monotonic curve: the ratio table is not guaranteed to increase every
// round (docs/BuildLog.md Phase 5), so a later dip back below the student's
// rank must not move the crossover - only the first reach counts.
{
  const i = findCrossoverIndex(rounds([500, 1300, 600, 700, 1400, 1500]), 1200);
  check(i === 1, `expected index 1 (first reach, ignoring the later dip), got ${i}`);
}

console.log("ok");
