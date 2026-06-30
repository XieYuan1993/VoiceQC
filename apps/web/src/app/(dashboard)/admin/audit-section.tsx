"use client";

import { ChevronDown, ChevronRight, Loader2, Search, X } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiCall, getApiErrorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { AuditList } from "@/lib/types";

const PAGE_SIZE = 25;

interface Filters {
  action: string;
  actor_email: string;
  object_type: string;
  since: string;
  until: string;
}

const EMPTY_FILTERS: Filters = {
  action: "",
  actor_email: "",
  object_type: "",
  since: "",
  until: "",
};

export function AuditSection() {
  // `applied` is what we actually query; `draft` is the form state.
  const [draft, setDraft] = React.useState<Filters>(EMPTY_FILTERS);
  const [applied, setApplied] = React.useState<Filters>(EMPTY_FILTERS);
  const [page, setPage] = React.useState(1);
  const [data, setData] = React.useState<AuditList | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [expanded, setExpanded] = React.useState<Set<number>>(new Set());

  const load = React.useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await apiCall("/api/admin/audit", "get", {
        params: {
          query: {
            action: applied.action || undefined,
            actor_email: applied.actor_email || undefined,
            object_type: applied.object_type || undefined,
            // <input type="date"> gives YYYY-MM-DD; the API treats these as
            // date bounds.
            since: applied.since || undefined,
            until: applied.until || undefined,
            page,
            page_size: PAGE_SIZE,
          },
        },
      });
      setData(res);
    } catch (e) {
      setLoadError(getApiErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [applied, page]);

  React.useEffect(() => {
    void load();
  }, [load]);

  function onApply(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPage(1);
    setExpanded(new Set());
    setApplied(draft);
  }

  function onClear() {
    setDraft(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setPage(1);
    setExpanded(new Set());
  }

  function toggle(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const items = data?.items ?? [];

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-base">Audit log</CardTitle>
        <CardDescription>
          Every privileged action — who, what, when, and from where. Read-only.
        </CardDescription>
        <form
          onSubmit={onApply}
          className="grid gap-3 pt-3 sm:grid-cols-2 lg:grid-cols-5 lg:items-end"
        >
          <div className="space-y-1">
            <Label htmlFor="aud-action" className="text-xs">
              Action prefix
            </Label>
            <Input
              id="aud-action"
              value={draft.action}
              onChange={(e) => setDraft({ ...draft, action: e.target.value })}
              placeholder="e.g. user."
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="aud-actor" className="text-xs">
              Actor email
            </Label>
            <Input
              id="aud-actor"
              value={draft.actor_email}
              onChange={(e) => setDraft({ ...draft, actor_email: e.target.value })}
              placeholder="admin@…"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="aud-object" className="text-xs">
              Object type
            </Label>
            <Input
              id="aud-object"
              value={draft.object_type}
              onChange={(e) => setDraft({ ...draft, object_type: e.target.value })}
              placeholder="e.g. user, sso_config"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="aud-since" className="text-xs">
              Since
            </Label>
            <Input
              id="aud-since"
              type="date"
              value={draft.since}
              onChange={(e) => setDraft({ ...draft, since: e.target.value })}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="aud-until" className="text-xs">
              Until
            </Label>
            <Input
              id="aud-until"
              type="date"
              value={draft.until}
              onChange={(e) => setDraft({ ...draft, until: e.target.value })}
            />
          </div>
          <div className="flex gap-2 sm:col-span-2 lg:col-span-5">
            <Button type="submit" size="sm">
              <Search className="mr-2 h-4 w-4" aria-hidden />
              Apply filters
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={onClear}>
              <X className="mr-2 h-4 w-4" aria-hidden />
              Clear
            </Button>
          </div>
        </form>
      </CardHeader>
      <CardContent className="p-0">
        {loadError !== null ? (
          <p className="px-6 pb-6 text-sm text-destructive">
            Failed to load audit log: {loadError}
          </p>
        ) : data === null ? (
          <p className="flex items-center gap-2 px-6 pb-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : items.length === 0 ? (
          <p className="px-6 pb-6 text-sm text-muted-foreground">
            No audit entries match these filters.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-8" />
                <TableHead className="whitespace-nowrap">When</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Object</TableHead>
                <TableHead>IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((row) => {
                const isOpen = expanded.has(row.id);
                const hasDetails =
                  row.details != null ||
                  row.user_agent != null ||
                  row.object_id != null;
                return (
                  <React.Fragment key={row.id}>
                    <TableRow>
                      <TableCell className="align-top">
                        {hasDetails ? (
                          <button
                            type="button"
                            onClick={() => toggle(row.id)}
                            aria-label={isOpen ? "Collapse details" : "Expand details"}
                            aria-expanded={isOpen}
                            className="text-muted-foreground hover:text-foreground"
                          >
                            {isOpen ? (
                              <ChevronDown className="h-4 w-4" aria-hidden />
                            ) : (
                              <ChevronRight className="h-4 w-4" aria-hidden />
                            )}
                          </button>
                        ) : null}
                      </TableCell>
                      <TableCell className="whitespace-nowrap tabular-nums">
                        {formatDateTime(row.occurred_at)}
                      </TableCell>
                      <TableCell>{row.actor_email ?? "—"}</TableCell>
                      <TableCell className="font-mono text-xs">{row.action}</TableCell>
                      <TableCell className="text-xs">
                        {row.object_type ?? "—"}
                        {row.object_id ? (
                          <span className="text-muted-foreground"> #{row.object_id}</span>
                        ) : null}
                      </TableCell>
                      <TableCell className="tabular-nums">{row.ip ?? "—"}</TableCell>
                    </TableRow>
                    {isOpen && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell />
                        <TableCell colSpan={5} className="space-y-2 py-3">
                          {row.user_agent && (
                            <p className="text-xs text-muted-foreground">
                              <span className="font-medium">User agent:</span>{" "}
                              {row.user_agent}
                            </p>
                          )}
                          {row.details != null && (
                            <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
                              {JSON.stringify(row.details, null, 2)}
                            </pre>
                          )}
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
      {data !== null && items.length > 0 && (
        <div className="flex items-center justify-between border-t px-6 py-3 text-sm">
          <span className="text-muted-foreground">
            {total.toLocaleString()} entr{total === 1 ? "y" : "ies"} · page {page} of{" "}
            {totalPages}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1 || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
