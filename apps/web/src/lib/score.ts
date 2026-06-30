// Shared QA-score colour banding: good >= 80, warn 50-79, bad < 50.
export type ScoreTone = "good" | "warn" | "bad" | "none";

export function scoreTone(v: number | null | undefined): ScoreTone {
  if (v == null) return "none";
  if (v >= 80) return "good";
  if (v >= 50) return "warn";
  return "bad";
}

const TEXT: Record<ScoreTone, string> = {
  good: "text-emerald-600 dark:text-emerald-400",
  warn: "text-amber-600 dark:text-amber-400",
  bad: "text-red-600 dark:text-red-400",
  none: "text-muted-foreground",
};

const BG: Record<ScoreTone, string> = {
  good: "bg-emerald-500",
  warn: "bg-amber-500",
  bad: "bg-red-500",
  none: "bg-muted-foreground/30",
};

export function scoreTextClass(v: number | null | undefined): string {
  return TEXT[scoreTone(v)];
}

export function scoreBgClass(v: number | null | undefined): string {
  return BG[scoreTone(v)];
}

// Score-band filter values used by the agent drill-down calls list.
export const SCORE_BANDS = [
  { value: "", label: "All scores" },
  { value: "high", label: "Good (80+)" },
  { value: "medium", label: "Fair (50–79)" },
  { value: "low", label: "Weak (<50)" },
] as const;

export function bandToRange(band: string): { min?: number; max?: number } {
  if (band === "high") return { min: 80 };
  if (band === "medium") return { min: 50, max: 79.999 };
  if (band === "low") return { max: 49.999 };
  return {};
}
