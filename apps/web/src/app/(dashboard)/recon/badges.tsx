// Shared badge maps + stat helpers for the reconciliation screens.
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { MATCH_STATUS_META, SEVERITY_META, describeStatus } from "@/lib/status-meta";

const SEVERITY_BADGE: Record<string, BadgeProps["variant"]> = {
  breach: "destructive",
  suspicious: "warning",
  info: "neutral",
};

const MATCH_BADGE: Record<string, BadgeProps["variant"]> = {
  auto_matched: "success",
  needs_review: "warning",
  unmatched: "neutral",
  confirmed: "info",
  rejected: "destructive",
  manual_linked: "violet",
};

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <Badge
      variant={SEVERITY_BADGE[severity] ?? "neutral"}
      title={describeStatus(SEVERITY_META, severity)}
    >
      {severity}
    </Badge>
  );
}

export function MatchStatusBadge({ status }: { status: string }) {
  return (
    <Badge
      variant={MATCH_BADGE[status] ?? "neutral"}
      className="whitespace-nowrap"
      title={describeStatus(MATCH_STATUS_META, status)}
    >
      {status.replaceAll("_", " ")}
    </Badge>
  );
}

export function formatScore(score: number | null): string {
  return score == null ? "—" : `${Math.round(score * 100)}%`;
}

/** Pull a numeric stat out of the loosely-typed run.stats dict. */
export function statNum(stats: { [key: string]: unknown } | null | undefined, key: string): number {
  const v = stats?.[key];
  return typeof v === "number" ? v : 0;
}
