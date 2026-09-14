import type { Trend } from "./api";

// Design.md, Copy rules: the label compares this key's cutoff movement to
// the field's typical movement (models/trend.py's DRIFT_MEDIAN_SLOPE), not
// to zero. A key whose own cutoff barely moved can still classify as
// Tightening if most colleges eased and this one did not, so the line must
// describe the comparison to other colleges, never assume the label means
// this cutoff itself moved in that direction. `slope` (the raw, undetrended
// fit) is what actually happened to this cutoff; the label is how that
// compares to the field. Rules.md section 5: never say more than is true.
export function supportingLine(trend: Trend): string {
  const slope = trend.slope ?? 0;
  const years = trend.years_used;

  switch (trend.label) {
    case "Tightening":
      return slope < 0
        ? `Cutoff has gotten more competitive over the last ${years} years, more than most colleges did.`
        : `Cutoff has eased less than most colleges over the last ${years} years, making it comparatively more competitive.`;
    case "Loosening":
      return slope > 0
        ? `Cutoff has gotten less competitive over the last ${years} years, more than most colleges did.`
        : `Cutoff has not tightened as much as most colleges over the last ${years} years, making it comparatively less competitive.`;
    case "Stable":
      if (slope > 0) return `Cutoff has eased slightly over the last ${years} years, in step with most colleges.`;
      if (slope < 0) return `Cutoff has tightened slightly over the last ${years} years, in step with most colleges.`;
      return `Cutoff has held steady over the last ${years} years, in step with most colleges.`;
    default:
      return "Not enough year-over-year data yet for a trend on this seat.";
  }
}
