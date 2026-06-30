import {
  AlertTriangle,
  ClipboardX,
  type LucideIcon,
  Megaphone,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { StatusMeta } from "@/lib/status-meta";

type BadgeVariant = "destructive" | "orange" | "violet" | "warning" | "neutral";
type ReasonMeta = { label: string; description: string; icon: LucideIcon; variant: BadgeVariant };

// Mirrors the review-need signals in the API (insights._review_reasons).
export const REVIEW_REASONS: Record<string, ReasonMeta> = {
  complaint: {
    label: "Complaint",
    description:
      "The customer expressed dissatisfaction or a grievance about the product, service, or staff.",
    icon: Megaphone,
    variant: "destructive",
  },
  wrong_answer: {
    label: "Wrong answer",
    description: "The agent gave an answer the knowledge base contradicts.",
    icon: XCircle,
    variant: "orange",
  },
  critical_risk: {
    label: "Critical risk",
    description: "The evaluation raised a risk flag of critical severity.",
    icon: AlertTriangle,
    variant: "violet",
  },
  low_adherence: {
    label: "Low adherence",
    description: "Weak script adherence — under 50% of the required checklist items were covered.",
    icon: ClipboardX,
    variant: "warning",
  },
};

// Display + filter order: most severe first.
export const REASON_ORDER = [
  "complaint",
  "wrong_answer",
  "critical_risk",
  "low_adherence",
] as const;

// For the shared StatusLegend.
export const REVIEW_REASON_LEGEND: StatusMeta[] = REASON_ORDER.map((k) => ({
  label: REVIEW_REASONS[k].label,
  description: REVIEW_REASONS[k].description,
}));

export function ReasonBadge({ reason }: { reason: string }) {
  const meta = REVIEW_REASONS[reason];
  if (!meta) return <Badge variant="neutral">{reason}</Badge>;
  const Icon = meta.icon;
  return (
    <Badge variant={meta.variant} className="gap-1 font-normal" title={meta.description}>
      <Icon aria-hidden className="h-3 w-3 shrink-0" />
      {meta.label}
    </Badge>
  );
}
