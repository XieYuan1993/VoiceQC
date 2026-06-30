"use client";

import { Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

const STATUSES = [
  "uploaded",
  "converting",
  "transcribing",
  "evaluating",
  "completed",
  "failed",
] as const;

// Filter state lives in the URL; the server page refetches on change.
// The parent keys this component on the params, so internal state resets
// whenever the URL changes from elsewhere.
export function RecordingFilters({
  status,
  callDate,
  q,
}: {
  status: string;
  callDate: string;
  q: string;
}) {
  const router = useRouter();
  const [search, setSearch] = React.useState(q);

  function apply(next: Partial<{ status: string; call_date: string; q: string }>) {
    const merged = { status, call_date: callDate, q, ...next };
    const params = new URLSearchParams();
    if (merged.status) params.set("status", merged.status);
    if (merged.call_date) params.set("call_date", merged.call_date);
    if (merged.q) params.set("q", merged.q);
    const qs = params.toString();
    router.replace(qs ? `/recordings?${qs}` : "/recordings");
  }

  const hasFilters = Boolean(status || callDate || q);

  // Live search: apply ~400ms after typing stops (Enter still applies immediately).
  React.useEffect(() => {
    const handle = setTimeout(() => {
      if (search.trim() !== q) apply({ q: search.trim() });
    }, 400);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <form
        className="relative"
        onSubmit={(e) => {
          e.preventDefault();
          apply({ q: search.trim() });
        }}
      >
        <Search
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search filename or transcript…"
          className="w-72 pl-9"
          aria-label="Search recordings"
        />
      </form>
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
        <Button variant="ghost" size="sm" onClick={() => router.replace("/recordings")}>
          <X className="mr-1 h-4 w-4" aria-hidden />
          Clear
        </Button>
      )}
    </div>
  );
}
