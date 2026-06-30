"use client";

import { X } from "lucide-react";
import { useRouter } from "next/navigation";

import { REASON_ORDER, REVIEW_REASONS } from "@/components/reason-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import type { ReviewQueueCounts } from "@/lib/types";
import { cn } from "@/lib/utils";

const SORTS = [
  { value: "score", label: "Lowest score" },
  { value: "recent", label: "Most recent" },
  { value: "severity", label: "Severity" },
] as const;

export function ReviewFilters({
  reason,
  agent,
  callDate,
  sort,
  counts,
  agents,
}: {
  reason: string;
  agent: string;
  callDate: string;
  sort: string;
  counts?: ReviewQueueCounts;
  agents: string[];
}) {
  const router = useRouter();

  function apply(next: Partial<{ reason: string; broker_ext: string; call_date: string; sort: string }>) {
    const merged = { reason, broker_ext: agent, call_date: callDate, sort, ...next };
    const params = new URLSearchParams();
    if (merged.reason) params.set("reason", merged.reason);
    if (merged.broker_ext) params.set("broker_ext", merged.broker_ext);
    if (merged.call_date) params.set("call_date", merged.call_date);
    if (merged.sort && merged.sort !== "score") params.set("sort", merged.sort);
    const qs = params.toString();
    router.replace(qs ? `/review?${qs}` : "/review");
  }

  const countFor = (key: string): number => {
    if (!counts) return 0;
    if (key === "") return counts.all;
    return (counts as unknown as Record<string, number>)[key] ?? 0;
  };

  const chips = [
    { key: "", label: "All", description: "Every flagged call in this project." },
    ...REASON_ORDER.map((k) => ({
      key: k,
      label: REVIEW_REASONS[k].label,
      description: REVIEW_REASONS[k].description,
    })),
  ];
  const hasFilters = Boolean(reason || agent || callDate || (sort && sort !== "score"));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {chips.map((c) => {
          const active = (reason || "") === c.key;
          return (
            <button
              key={c.key || "all"}
              type="button"
              onClick={() => apply({ reason: c.key })}
              aria-pressed={active}
              title={c.description}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm transition-colors",
                active
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:bg-muted/60",
              )}
            >
              {c.label}
              <span className="tabular-nums text-xs text-muted-foreground">{countFor(c.key)}</span>
            </button>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={agent}
          onChange={(e) => apply({ broker_ext: e.target.value })}
          wrapperClassName="w-44"
          aria-label="Filter by agent"
        >
          <option value="">All agents</option>
          {agents.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </Select>
        <Input
          type="date"
          value={callDate}
          onChange={(e) => apply({ call_date: e.target.value })}
          className="w-44"
          aria-label="Filter by call date"
        />
        <Select
          value={sort}
          onChange={(e) => apply({ sort: e.target.value })}
          wrapperClassName="w-44"
          aria-label="Sort"
        >
          {SORTS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </Select>
        {hasFilters && (
          <Button variant="ghost" size="sm" onClick={() => router.replace("/review")}>
            <X className="mr-1 h-4 w-4" aria-hidden />
            Clear
          </Button>
        )}
      </div>
    </div>
  );
}
