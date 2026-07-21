import type { CSSProperties, ReactNode } from "react";
import { C, fMono } from "../lib/tokens";

export function Eyebrow({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div style={{
      fontFamily: fMono, fontSize: 11, fontWeight: 500,
      letterSpacing: "0.08em", textTransform: "uppercase",
      color: C.primary, marginBottom: 10, ...style,
    }}>{children}</div>
  );
}
