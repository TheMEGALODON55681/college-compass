import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { C, fBody, fMono } from "../lib/tokens";
import type { CutoffHistoryPoint } from "../lib/api";

// Plain, non-reversed rank axis on purpose (Phases.md): a reversed axis
// makes "line going down" ambiguous about whether things are getting better
// or worse. The label below says plainly what a lower number means instead.
export function CutoffTrendChart({ history }: { history: CutoffHistoryPoint[] }) {
  return (
    <div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={history} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={C.line} vertical={false} />
          <XAxis dataKey="year" tick={{ fontFamily: fMono, fontSize: 11, fill: C.ink500 }} axisLine={{ stroke: C.line }} tickLine={false} />
          <YAxis
            tick={{ fontFamily: fMono, fontSize: 11, fill: C.ink500 }}
            axisLine={{ stroke: C.line }}
            tickLine={false}
            width={56}
            tickFormatter={(v: number) => v.toLocaleString("en-IN")}
          />
          <Tooltip
            formatter={(value: number) => [value.toLocaleString("en-IN"), "Closing rank"]}
            labelFormatter={(year) => `${year}`}
            contentStyle={{ fontFamily: fMono, fontSize: 12, border: `1px solid ${C.line}`, borderRadius: 8 }}
          />
          <Line type="monotone" dataKey="closing_rank" stroke={C.primary} strokeWidth={2} dot={{ r: 3, fill: C.primary }} activeDot={{ r: 5 }} />
        </LineChart>
      </ResponsiveContainer>
      <p style={{ fontFamily: fBody, fontSize: 13, color: C.ink500, marginTop: 10, marginBottom: 0, lineHeight: 1.6 }}>
        A lower closing rank means the seat was more competitive that year - fewer ranks got in.
      </p>
    </div>
  );
}
