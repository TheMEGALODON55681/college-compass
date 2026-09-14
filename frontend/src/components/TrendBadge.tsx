import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { C, fBody, fMono } from "../lib/tokens";
import type { Trend, TrendLabel } from "../lib/api";
import { supportingLine } from "../lib/trendCopy";

// Design.md: no red/green traffic light here. Tightening is not bad news
// and loosening is not good news - both describe the college, not the
// student - so all three directions share one neutral treatment and differ
// only by a directional mark. Insufficient history renders in the same
// badge shape, muted, with no mark: a quiet absence, not a warning.
const DIRECTION_ICON: Partial<Record<TrendLabel, typeof ArrowUpRight>> = {
  Tightening: ArrowDownRight,
  Stable: Minus,
  Loosening: ArrowUpRight,
};

// Label only on compact result rows, label plus supporting line on the
// detail screen (Design.md). No entrance animation - this is metadata on a
// row, not an event.
export function TrendBadge({ trend, showLine = false }: { trend: Trend | null | undefined; showLine?: boolean }) {
  if (!trend) return null;
  const Icon = DIRECTION_ICON[trend.label];
  const muted = trend.label === "Insufficient history";

  return (
    <div>
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        fontFamily: fMono, fontSize: 11, fontWeight: 500, letterSpacing: "0.04em",
        color: muted ? C.ink300 : C.ink700,
        background: C.paper, border: `1px solid ${C.line}`,
        borderRadius: 999, padding: "3px 10px", whiteSpace: "nowrap",
      }}>
        {Icon && <Icon size={12} color={C.ink500} />}
        {trend.label}
      </span>
      {showLine && (
        <p style={{ fontFamily: fBody, fontSize: 13, color: C.ink500, marginTop: 8, marginBottom: 0, lineHeight: 1.6 }}>
          {supportingLine(trend)}
        </p>
      )}
    </div>
  );
}
