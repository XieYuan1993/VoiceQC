"use client";

import { X } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

const STATUSES = ["open", "processing", "completed", "completed_with_errors", "failed"] as const;

// Filter state lives in the URL; the server page refetches on change.
export function BatchFilters({
  status,
  q,
  from,
  to,
}: {
  status: string;
  q: string;
  from: string;
  to: string;
}) {
  const router = useRouter();
  const [search, setSearch] = React.useState(q);

  function apply(next: Partial<{ status: string; q: string; from: string; to: string }>) {
    const merged = { status, q, from, to, ...next };
    const params = new URLSearchParams();
    if (merged.status) params.set("status", merged.status);
    if (merged.q) params.set("q", merged.q);
    if (merged.from) params.set("from", merged.from);
    if (merged.to) params.set("to", merged.to);
    const qs = params.toString();
    router.replace(qs ? `/batches?${qs}` : "/batches");
  }

  const hasFilters = Boolean(status || q || from || to);

  // Live search: apply ~400ms after typing stops.
  React.useEffect(() => {
    const handle = setTimeout(() => {
      if (search.trim() !== q) apply({ q: search.trim() });
    }, 400);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search batch name…"
        className="w-56"
        aria-label="Search batches by name"
      />
      <Select
        value={status}
        onChange={(e) => apply({ status: e.target.value })}
        wrapperClassName="w-48"
        aria-label="Filter by status"
      >
        <option value="">All statuses</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s.replaceAll("_", " ")}
          </option>
        ))}
      </Select>
      <div className="flex items-center gap-1.5">
        <Input
          type="date"
          value={from}
          onChange={(e) => apply({ from: e.target.value })}
          className="w-40"
          aria-label="Batch date from"
        />
        <span className="text-sm text-muted-foreground">to</span>
        <Input
          type="date"
          value={to}
          onChange={(e) => apply({ to: e.target.value })}
          className="w-40"
          aria-label="Batch date to"
        />
      </div>
      {hasFilters && (
        <Button variant="ghost" size="sm" onClick={() => router.replace("/batches")}>
          <X className="mr-1 h-4 w-4" aria-hidden />
          Clear
        </Button>
      )}
    </div>
  );
}
