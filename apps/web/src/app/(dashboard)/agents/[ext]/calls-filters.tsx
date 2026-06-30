"use client";

import { X } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { SCORE_BANDS } from "@/lib/score";

const STATUSES = [
  "uploaded",
  "converting",
  "transcribing",
  "evaluating",
  "completed",
  "failed",
] as const;

// Filter state lives in the URL; the server page refetches on change.
export function AgentCallsFilters({
  ext,
  status,
  callDate,
  band,
}: {
  ext: string;
  status: string;
  callDate: string;
  band: string;
}) {
  const router = useRouter();
  const base = `/agents/${encodeURIComponent(ext)}`;

  function apply(next: Partial<{ status: string; call_date: string; band: string }>) {
    const merged = { status, call_date: callDate, band, ...next };
    const params = new URLSearchParams();
    if (merged.status) params.set("status", merged.status);
    if (merged.call_date) params.set("call_date", merged.call_date);
    if (merged.band) params.set("band", merged.band);
    const qs = params.toString();
    router.replace(qs ? `${base}?${qs}` : base);
  }

  const hasFilters = Boolean(status || callDate || band);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={band}
        onChange={(e) => apply({ band: e.target.value })}
        wrapperClassName="w-40"
        aria-label="Filter by score band"
      >
        {SCORE_BANDS.map((b) => (
          <option key={b.value} value={b.value}>
            {b.label}
          </option>
        ))}
      </Select>
      <Select
        value={status}
        onChange={(e) => apply({ status: e.target.value })}
        wrapperClassName="w-44"
        aria-label="Filter by status"
      >
        <option value="">All statuses</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
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
      {hasFilters && (
        <Button variant="ghost" size="sm" onClick={() => router.replace(base)}>
          <X className="mr-1 h-4 w-4" aria-hidden />
          Clear
        </Button>
      )}
    </div>
  );
}
