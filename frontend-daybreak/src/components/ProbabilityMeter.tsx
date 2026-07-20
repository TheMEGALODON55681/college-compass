import { useEffect, useState } from "react";
import { C, STATUS, fMono } from "../lib/tokens";
import type { Tier } from "../lib/types";

export function ProbabilityMeter({ probability, status, delay = 0 }: { probability: number; status: Tier; delay?: number }) {
  const [filled, setFilled] = useState(false);
  const [count, setCount] = useState(0);
  const s = STATUS[status];

  useEffect(() => {
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) { setFilled(true); setCount(probability); return; }
    const t = setTimeout(() => {
      setFilled(true);
      const start = Date.now();
      const dur = 1000;
      const tick = () => {
        const p = Math.min((Date.now() - start) / dur, 1);
        const eased = 1 - Math.pow(1 - p, 3);
        setCount(Math.round(eased * probability));
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }, delay);
    return () => clearTimeout(t);
  }, [probability, delay]);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div style={{ flex: 1, height: 6, background: C.line, borderRadius: 999, overflow: "hidden" }}>
        <div style={{
          width: filled ? `${probability}%` : "0%",
          height: "100%", background: s.solid, borderRadius: 999,
          transition: "width 1000ms cubic-bezier(0.22, 0.61, 0.36, 1)",
        }} />
      </div>
      <span style={{ fontFamily: fMono, fontSize: 14, fontWeight: 500, color: s.text, minWidth: 38, textAlign: "right" }}>
        {count}%
      </span>
    </div>
  );
}
