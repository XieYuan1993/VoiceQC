import { scoreBgClass, scoreTextClass } from "@/lib/score";
import { cn } from "@/lib/utils";

/** A right-aligned number with a thin proportional bar beneath it (0–100 scale),
 * coloured by the shared score band. Used in scorecard tables and headers. */
export function MetricBar({
  value,
  suffix = "",
  className,
}: {
  value: number | null | undefined;
  suffix?: string;
  className?: string;
}) {
  const pct = value == null ? 0 : Math.max(0, Math.min(100, value));
  return (
    <div className={cn("min-w-[56px] space-y-1", className)}>
      <span className={cn("block text-right font-medium tabular-nums", scoreTextClass(value))}>
        {value == null ? "—" : `${Math.round(value)}${suffix}`}
      </span>
      <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full", scoreBgClass(value))}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
