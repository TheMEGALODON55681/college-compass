import type { Tier } from "./types";

export const C = {
  paper: "#FBFAF6",
  surface: "#FFFFFF",
  line: "#E8E5DE",
  ink900: "#14213D",
  ink700: "#2B3452",
  ink500: "#5A6480",
  ink300: "#9AA2B8",
  primary: "#2A5FC0",
  primaryHover: "#1E4A99",
  primaryTint: "#EAF0FB",
  signature: "#6C5CE0",
  signatureTint: "#EEEBFB",
  washWarm: "#FCEFE6",
  washCool: "#EEF1FC",
  primaryLight: "#7FB3E8",
} as const;

export const STATUS: Record<Tier, { solid: string; tint: string; text: string; label: string }> = {
  likely: { solid: "#1B9C6B", tint: "#E4F4EC", text: "#0E6B47", label: "Likely" },
  fair: { solid: "#C67F14", tint: "#FBF0DA", text: "#8A570A", label: "Fair chance" },
  reach: { solid: "#D0563C", tint: "#FBE8E2", text: "#983320", label: "Reach" },
};

export const shadow = {
  rest: "0 1px 2px rgba(20,33,61,0.05), 0 1px 3px rgba(20,33,61,0.04)",
  raised: "0 8px 24px rgba(20,33,61,0.10)",
  signature: "0 12px 40px rgba(108,92,224,0.14)",
};

export const easeOut = [0.22, 0.61, 0.36, 1] as const;

export const fDisplay = "'Space Grotesk', sans-serif";
export const fBody = "'Plus Jakarta Sans', sans-serif";
export const fMono = "'IBM Plex Mono', monospace";
