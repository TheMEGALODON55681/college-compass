// Runnable check for trendCopy.ts: asserts each label's supporting line
// stays consistent with the sign of the raw slope, so copy and classifier
// (models/trend.py) cannot drift apart the way they did before this file
// existed (see docs/BuildLog.md). Plain assertions, no test framework:
// this repo's frontend has none installed, and Node runs a .ts file like
// this one directly (see README's build-the-database section neighbor,
// the Quickstart section, for the project's "use what's already here"
// stance on dependencies).
//
// Run with: node src/lib/trendCopy.test.ts

import type { Trend } from "./api.ts";
import { supportingLine } from "./trendCopy.ts";

function trend(overrides: Partial<Trend>): Trend {
  return { label: "Stable", years_used: 4, slope: 0, residual_slope: 0, reason: null, ...overrides };
}

function check(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

// Tightening, raw slope negative: the cutoff itself literally got more
// competitive, and the line should say so plainly.
{
  const line = supportingLine(trend({ label: "Tightening", slope: -420 }));
  check(line.includes("gotten more competitive"), `expected "gotten more competitive", got: ${line}`);
  check(!line.includes("eased"), `should not claim easing for a negative slope, got: ${line}`);
}

// Tightening with a flat or slightly positive raw slope: this is the bug
// this whole change fixes. A raw-flat key can still classify Tightening
// because the field eased and this one did not, so the line must not claim
// the cutoff itself moved toward more competitive.
{
  const flat = supportingLine(trend({ label: "Tightening", slope: 0 }));
  check(!flat.includes("gotten more competitive"), `flat slope must not claim it got more competitive, got: ${flat}`);
  check(flat.includes("comparatively more competitive"), `expected a comparative claim, got: ${flat}`);

  const slightlyUp = supportingLine(trend({ label: "Tightening", slope: 150 }));
  check(!slightlyUp.includes("gotten more competitive"), `positive slope must not claim it got more competitive, got: ${slightlyUp}`);
  check(slightlyUp.includes("eased less than most colleges"), `expected "eased less than", got: ${slightlyUp}`);
}

// Loosening, raw slope positive: the cutoff itself literally got easier.
{
  const line = supportingLine(trend({ label: "Loosening", slope: 600 }));
  check(line.includes("gotten less competitive"), `expected "gotten less competitive", got: ${line}`);
}

// Loosening with a flat or negative raw slope (defensive: today's constants
// make this unreachable, but the copy must not overclaim if a reingest
// ever changes DRIFT_MEDIAN_SLOPE/NEUTRAL_BAND_FRACTION and it becomes
// reachable).
{
  const line = supportingLine(trend({ label: "Loosening", slope: 0 }));
  check(!line.includes("gotten less competitive"), `flat slope must not claim it got less competitive, got: ${line}`);
  check(line.includes("comparatively less competitive"), `expected a comparative claim, got: ${line}`);
}

// Stable: the label always means "in step with the field", but the line
// should still name what the raw slope actually did.
{
  const easing = supportingLine(trend({ label: "Stable", slope: 80 }));
  check(easing.includes("eased slightly"), `expected "eased slightly", got: ${easing}`);

  const tightening = supportingLine(trend({ label: "Stable", slope: -80 }));
  check(tightening.includes("tightened slightly"), `expected "tightened slightly", got: ${tightening}`);

  const flat = supportingLine(trend({ label: "Stable", slope: 0 }));
  check(flat.includes("held steady"), `expected "held steady", got: ${flat}`);
}

// years_used is always interpolated into the line for the three real
// labels, never hardcoded.
{
  const line = supportingLine(trend({ label: "Tightening", slope: -1, years_used: 7 }));
  check(line.includes("7 years"), `expected years_used=7 in the line, got: ${line}`);
}

console.log("ok");
