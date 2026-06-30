import { Badge, type BadgeProps } from "@/components/ui/badge";
import { RECORDING_STATUS_META, describeStatus } from "@/lib/status-meta";
import type { BatchCounts } from "@/lib/types";
import { cn } from "@/lib/utils";

type Variant = BadgeProps["variant"];

// Batch statuses: open/processing/completed/completed_with_errors/failed.
// Recording statuses: uploaded/converting/transcribing/evaluating/completed/failed.
// Txn imports add pending; recon runs add running.
const STATUS_VARIANTS: Record<string, Variant> = {
  open: "info",
  processing: "warning",
  completed: "success",
  completed_with_errors: "orange",
  failed: "destructive",
  uploaded: "neutral",
  converting: "warning",
  transcribing: "info",
  evaluating: "violet",
  pending: "neutral",
  running: "warning",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <Badge
      variant={STATUS_VARIANTS[status] ?? "neutral"}
      className={cn("whitespace-nowrap", className)}
      title={describeStatus(RECORDING_STATUS_META, status)}
    >
      {status.replaceAll("_", " ")}
    </Badge>
  );
}

const STAGES: ReadonlyArray<{ key: keyof BatchCounts; variant: Variant }> = [
  { key: "uploaded", variant: "neutral" },
  { key: "converting", variant: "warning" },
  { key: "transcribing", variant: "info" },
  { key: "evaluating", variant: "violet" },
  { key: "completed", variant: "success" },
  { key: "failed", variant: "destructive" },
];

/** Per-stage recording counts as colored chips. */
export function StageChips({
  counts,
  hideZero = false,
  className,
}: {
  counts: BatchCounts | null | undefined;
  hideZero?: boolean;
  className?: string;
}) {
  if (!counts) return null;
  const visible = STAGES.filter((s) => !hideZero || counts[s.key] > 0);
  if (visible.length === 0) return null;
  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {visible.map((s) => (
        <Badge
          key={s.key}
          variant={s.variant}
          className={cn("gap-1 whitespace-nowrap", counts[s.key] === 0 && "opacity-40")}
        >
          <span className="font-semibold tabular-nums">{counts[s.key]}</span>
          {s.key}
        </Badge>
      ))}
    </div>
  );
}
