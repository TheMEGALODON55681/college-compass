import { STATUS, fMono } from "../lib/tokens";
import type { Tier } from "../lib/types";

export function StatusPill({ status }: { status: Tier }) {
  const s = STATUS[status];
  return (
    <span style={{
      background: s.tint, color: s.text,
      fontFamily: fMono, fontSize: 11, fontWeight: 500,
      letterSpacing: "0.08em", textTransform: "uppercase",
      padding: "3px 10px", borderRadius: 999, whiteSpace: "nowrap",
    }}>{s.label}</span>
  );
}
