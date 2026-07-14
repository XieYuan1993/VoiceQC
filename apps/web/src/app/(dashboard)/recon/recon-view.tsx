"use client";

import { Download, Loader2, MessageSquare, Play, RefreshCw } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { API_URL, apiCall, getApiErrorMessage } from "@/lib/api";
import { formatDateTime, todayISO } from "@/lib/format";
import { StatusLegend } from "@/components/status-legend";
import { RECON_RESULT_LEGEND, RECON_RESULT_META, describeStatus } from "@/lib/status-meta";
import type { ReconItem, ReconItemList, ReconRun } from "@/lib/types";
import { cn } from "@/lib/utils";

import { MatchStatusBadge, SeverityBadge, formatScore, statNum } from "./badges";
import { ReviewDrawer } from "./review-drawer";

const POLL_MS = 5000;
const ITEMS_PAGE_SIZE = 50;

type Bucket = "matched" | "txn_no_recording" | "recording_no_txn";

const TABS: ReadonlyArray<{ key: Bucket; label: string }> = [
  { key: "matched", label: "Matched" },
  { key: "txn_no_recording", label: "Txn without recording" },
  { key: "recording_no_txn", label: "Recording without txn" },
];

const MATCH_STATUSES = [
  "auto_matched",
  "needs_review",
  "unmatched",
  "confirmed",
  "rejected",
  "manual_linked",
] as const;

const UNMATCHED_REASONS = {
  no_broker_recordings_day: "Broker has no calls that day",
  no_recordings_in_window: "No broker call in time window",
  no_matching_recording: "Calls found, none matched",
} as const;

type UnmatchedReason = keyof typeof UNMATCHED_REASONS;

interface DiagnosticCandidate {
  recording_id: string;
  original_filename?: string | null;
  conflicts?: Array<{ field: string; transaction: unknown; recording: unknown }>;
}

function itemDiagnostics(item: ReconItem) {
  const raw = item.score_breakdown as {
    unmatched_reason?: UnmatchedReason;
    candidates?: DiagnosticCandidate[];
    conflict_fields?: DiagnosticCandidate["conflicts"];
  };
  return {
    reason: raw.unmatched_reason,
    candidate: raw.candidates?.[0],
    conflicts: raw.conflict_fields ?? raw.candidates?.[0]?.conflicts ?? [],
  };
}

function conflictLabel(conflict: NonNullable<DiagnosticCandidate["conflicts"]>[number]) {
  if (conflict.field === "broker") {
    return `broker: transaction ${String(conflict.transaction ?? "unknown")} vs recording ${String(conflict.recording ?? "unknown")}`;
  }
  return `${conflict.field}: ${String(conflict.transaction ?? "unknown")} vs ${String(conflict.recording ?? "unknown")}`;
}

interface RunRange {
  from: string;
  to: string;
}

function runRangeLabel(run: Pick<ReconRun, "trade_date" | "trade_date_from" | "trade_date_to">) {
  const from = run.trade_date_from || run.trade_date;
  const to = run.trade_date_to || from;
  return from === to ? from : `${from} - ${to}`;
}

function RunStatsChips({ stats }: { stats: ReconRun["stats"] }) {
  if (!stats) return null;
  const chips: ReadonlyArray<{ label: string; key: string; variant: Parameters<typeof Badge>[0]["variant"] }> = [
    { label: "auto", key: "matched_auto", variant: "success" },
    { label: "review", key: "matched_needs_review", variant: "warning" },
    { label: "breach", key: "txn_no_recording", variant: "destructive" },
    { label: "suspicious", key: "recording_no_txn_suspicious", variant: "orange" },
    { label: "info", key: "recording_no_txn_info", variant: "neutral" },
    { label: "carried", key: "decisions_carried_forward", variant: "violet" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chips.map((c) => {
        const n = statNum(stats, c.key);
        return (
          <Badge
            key={c.key}
            variant={c.variant}
            className={cn("gap-1 whitespace-nowrap", n === 0 && "opacity-40")}
            title={describeStatus(RECON_RESULT_META, c.key)}
          >
            <span className="font-semibold tabular-nums">{n}</span>
            {c.label}
          </Badge>
        );
      })}
    </div>
  );
}

function StatTile({
  label,
  value,
  detail,
  tone,
  onClick,
}: {
  label: string;
  value: number;
  detail?: string;
  tone?: string;
  onClick?: () => void;
}) {
  const inner = (
    <>
      <p className={cn("text-2xl font-semibold tabular-nums", tone)}>{value}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
      {detail && <p className="mt-1 text-xs text-muted-foreground">{detail}</p>}
    </>
  );
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className="rounded-lg border bg-card p-3 text-left transition-colors hover:border-primary/50 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {inner}
      </button>
    );
  }
  return <div className="rounded-lg border bg-card p-3">{inner}</div>;
}

export function ReconView({ canManage }: { canManage: boolean }) {
  const [runs, setRuns] = React.useState<ReconRun[] | null>(null);
  const [runsError, setRunsError] = React.useState<string | null>(null);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const [tradeDateFrom, setTradeDateFrom] = React.useState(todayISO());
  const [tradeDateTo, setTradeDateTo] = React.useState(todayISO());
  const [creating, setCreating] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);

  const [tab, setTab] = React.useState<Bucket>("matched");
  const [page, setPage] = React.useState(1);
  const [matchStatus, setMatchStatus] = React.useState("");
  const [severity, setSeverity] = React.useState("");
  const [unmatchedReason, setUnmatchedReason] = React.useState("");
  const [items, setItems] = React.useState<ReconItemList | null>(null);
  const [itemsError, setItemsError] = React.useState<string | null>(null);

  const [drawerId, setDrawerId] = React.useState<string | null>(null);
  const [exporting, setExporting] = React.useState(false);

  const runsRef = React.useRef<ReconRun[] | null>(null);

  const loadRuns = React.useCallback(async () => {
    try {
      const list = await apiCall("/api/recon/runs", "get");
      runsRef.current = list;
      setRuns(list);
      setRunsError(null);
    } catch (e) {
      // Keep stale data on transient poll failures.
      if (runsRef.current === null) setRunsError(getApiErrorMessage(e));
    }
  }, []);

  React.useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  // Default to the most recent run once the list arrives.
  React.useEffect(() => {
    if (selectedId === null && runs !== null && runs.length > 0) setSelectedId(runs[0].id);
  }, [runs, selectedId]);

  const selected = runs?.find((r) => r.id === selectedId) ?? null;

  const goBucket = React.useCallback((b: Bucket, status = "", itemSeverity = "") => {
    setTab(b);
    setMatchStatus(status);
    setSeverity(itemSeverity);
    setUnmatchedReason("");
    setPage(1);
    setDrawerId(null);
  }, []);

  // When a run is opened, jump to the first bucket that has findings — so the
  // reviewer isn't staring at an empty "Matched" tab when all the action is in
  // "Recording without txn".
  React.useEffect(() => {
    const s = runsRef.current?.find((r) => r.id === selectedId)?.stats ?? null;
    if (s === null) return;
    const matched =
      statNum(s, "matched_auto") +
      statNum(s, "matched_needs_review") +
      statNum(s, "decisions_carried_forward");
    const txnNo = statNum(s, "txn_no_recording");
    const recNo = statNum(s, "recording_no_txn_suspicious") + statNum(s, "recording_no_txn_info");
    goBucket(
      matched > 0 ? "matched" : txnNo > 0 ? "txn_no_recording" : recNo > 0 ? "recording_no_txn" : "matched",
    );
  }, [selectedId, goBucket]);

  // Poll while any run is still being computed.
  const anyRunning = runs?.some((r) => r.status === "running") ?? false;
  React.useEffect(() => {
    if (!anyRunning) return;
    const timer = window.setInterval(() => void loadRuns(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [anyRunning, loadRuns]);

  // Reset item paging when switching run or tab.
  React.useEffect(() => {
    setPage(1);
    setMatchStatus("");
    setUnmatchedReason("");
    setDrawerId(null);
    setSeverity("");
  }, [selectedId]);

  const selectedStatus = selected?.status;
  const loadItems = React.useCallback(async () => {
    if (selectedId === null) return;
    try {
      const list = await apiCall("/api/recon/runs/{run_id}/items", "get", {
        params: {
          path: { run_id: selectedId },
          query: {
            bucket: tab,
            match_status: matchStatus || undefined,
            severity: severity || undefined,
            unmatched_reason: unmatchedReason || undefined,
            page,
            page_size: ITEMS_PAGE_SIZE,
          },
        },
      });
      setItems(list);
      setItemsError(null);
    } catch (e) {
      setItemsError(getApiErrorMessage(e));
    }
  }, [selectedId, tab, page, matchStatus, severity, unmatchedReason]);

  React.useEffect(() => {
    setItems(null);
    setItemsError(null);
    if (selectedId === null || selectedStatus !== "completed") return;
    void loadItems();
  }, [loadItems, selectedId, selectedStatus]);

  async function runFor(range: RunRange) {
    if (!range.from || !range.to) return;
    setCreating(true);
    setActionError(null);
    try {
      const run = await apiCall("/api/recon/runs", "post", {
        body: {
          trade_date_from: range.from,
          trade_date_to: range.to,
        },
      });
      setSelectedId(run.id);
      await loadRuns();
    } catch (e) {
      setActionError(getApiErrorMessage(e));
    } finally {
      setCreating(false);
    }
  }

  // Re-running a date creates a fresh run; the worker carries prior confirm/
  // reject/manual-link decisions forward, so a re-run never loses review work.
  function onRun() {
    if (!tradeDateFrom || !tradeDateTo) return;
    void runFor({ from: tradeDateFrom, to: tradeDateTo });
  }

  // Cross-origin API (:7870) — an <a href> would not carry the session cookie
  // reliably, so fetch with credentials and download the blob.
  async function onExport() {
    if (selected === null) return;
    setExporting(true);
    setActionError(null);
    try {
      const res = await fetch(`${API_URL}/api/recon/runs/${selected.id}/export.csv`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error(`Export failed (HTTP ${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `recon-${runRangeLabel(selected)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setActionError(getApiErrorMessage(e));
    } finally {
      setExporting(false);
    }
  }

  function onItemUpdated(updated: ReconItem) {
    setItems((prev) =>
      prev === null
        ? prev
        : { ...prev, items: prev.items.map((i) => (i.id === updated.id ? updated : i)) },
    );
    // Manual links can resolve sibling items too — refresh quietly.
    void loadItems();
  }

  const drawerItem = items?.items.find((i) => i.id === drawerId) ?? null;
  const pageCount = items === null ? 1 : Math.max(1, Math.ceil(items.total / ITEMS_PAGE_SIZE));
  const stats = selected?.stats ?? null;
  const txnsTotal = stats !== null ? statNum(stats, "txns_total") : 0;
  const txnsUnmapped = stats !== null ? statNum(stats, "txn_no_recording") : 0;
  const coveragePct = txnsTotal > 0 ? Math.round(((txnsTotal - txnsUnmapped) / txnsTotal) * 100) : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Reconciliation</h1>
          <p className="text-sm text-muted-foreground">
            Trades without a matching call recording, and vice versa.
          </p>
        </div>
        {canManage && (
          <div className="flex flex-wrap items-end gap-2">
            <div className="space-y-1">
              <Label htmlFor="recon-date-from" className="text-xs text-muted-foreground">
                From
              </Label>
              <Input
                id="recon-date-from"
                type="date"
                value={tradeDateFrom}
                onChange={(e) => {
                  setTradeDateFrom(e.target.value);
                  if (tradeDateTo < e.target.value) setTradeDateTo(e.target.value);
                }}
                className="w-40"
                aria-label="Trade date range start"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="recon-date-to" className="text-xs text-muted-foreground">
                To
              </Label>
              <Input
                id="recon-date-to"
                type="date"
                value={tradeDateTo}
                min={tradeDateFrom}
                onChange={(e) => setTradeDateTo(e.target.value)}
                className="w-40"
                aria-label="Trade date range end"
              />
            </div>
            <Button onClick={onRun} disabled={creating || !tradeDateFrom || !tradeDateTo}>
              {creating ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Play className="mr-2 h-4 w-4" aria-hidden />
              )}
              Run reconciliation
            </Button>
          </div>
        )}
      </div>

      {actionError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive">
          {actionError}
        </div>
      )}

      <Card className="overflow-hidden">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            Runs
            {anyRunning && (
              <Loader2
                className="h-4 w-4 animate-spin text-muted-foreground"
                aria-label="Run in progress"
              />
            )}
          </CardTitle>
          <CardDescription>One run per trade date — click a row to inspect it.</CardDescription>
          <StatusLegend
            items={RECON_RESULT_LEGEND}
            label="What do the results mean?"
            className="pt-1"
          />
        </CardHeader>
        <CardContent className="p-0">
          {runsError !== null ? (
            <p className="px-6 pb-6 text-sm text-destructive">Failed to load runs: {runsError}</p>
          ) : runs === null ? (
            <p className="flex items-center gap-2 px-6 pb-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
            </p>
          ) : runs.length === 0 ? (
            <p className="px-6 pb-6 text-sm text-muted-foreground">
              No runs yet
              {canManage ? " — pick a trade date above and run reconciliation." : "."}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Trade date(s)</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Results</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((r) => (
                  <TableRow
                    key={r.id}
                    tabIndex={0}
                    onClick={() => setSelectedId(r.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") setSelectedId(r.id);
                    }}
                    aria-selected={r.id === selectedId}
                    className={cn(
                      "cursor-pointer focus-visible:bg-muted/50 focus-visible:outline-none",
                      r.id === selectedId && "bg-muted/60 hover:bg-muted/60",
                    )}
                  >
                    <TableCell className="whitespace-nowrap font-medium">{runRangeLabel(r)}</TableCell>
                    <TableCell>
                      <StatusBadge status={r.status} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {formatDateTime(r.started_at)}
                    </TableCell>
                    <TableCell>
                      {r.status === "failed" ? (
                        <span className="block max-w-md truncate text-sm text-destructive" title={r.error ?? undefined}>
                          {r.error ?? "failed"}
                        </span>
                      ) : (
                        <RunStatsChips stats={r.stats} />
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {selected !== null && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="flex items-center gap-3 text-lg font-semibold">
              Run · {runRangeLabel(selected)}
              <StatusBadge status={selected.status} />
              {selected.status === "running" && (
                <Loader2
                  className="h-4 w-4 animate-spin text-muted-foreground"
                  aria-label="Running"
                />
              )}
            </h2>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  void runFor({
                    from: selected.trade_date_from || selected.trade_date,
                    to: selected.trade_date_to || selected.trade_date_from || selected.trade_date,
                  })
                }
                disabled={creating || selected.status === "running"}
                title="Re-run reconciliation for this date range with the latest trades and calls"
              >
                {creating ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
                )}
                Re-run
              </Button>
              <Button variant="outline" size="sm" onClick={onExport} disabled={exporting}>
                {exporting ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Download className="mr-2 h-4 w-4" aria-hidden />
                )}
                Export CSV
              </Button>
            </div>
          </div>

          {selected.status === "failed" && selected.error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive">
              Run failed: {selected.error}
            </div>
          )}

          {coveragePct !== null && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border bg-card px-4 py-3">
              <span className="text-2xl font-semibold tabular-nums">{coveragePct}%</span>
              <span className="text-sm text-muted-foreground">of trades mapped to a call</span>
              <span className="text-sm tabular-nums text-muted-foreground">
                · {txnsTotal - txnsUnmapped} of {txnsTotal}
              </span>
              {txnsUnmapped > 0 && (
                <button
                  type="button"
                  onClick={() => goBucket("txn_no_recording")}
                  className="text-sm font-medium text-red-600 hover:underline dark:text-red-400"
                >
                  · {txnsUnmapped} unmapped →
                </button>
              )}
            </div>
          )}
          {stats !== null && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-7">
              <StatTile
                label="Auto matched"
                value={statNum(stats, "matched_auto")}
                tone="text-emerald-600 dark:text-emerald-400"
                onClick={() => goBucket("matched", "auto_matched")}
              />
              <StatTile
                label="Needs review"
                value={statNum(stats, "matched_needs_review")}
                tone="text-amber-600 dark:text-amber-400"
                onClick={() => goBucket("matched", "needs_review")}
              />
              <StatTile
                label="Txn without recording"
                value={statNum(stats, "txn_no_recording")}
                tone="text-red-600 dark:text-red-400"
                onClick={() => goBucket("txn_no_recording")}
              />
              <StatTile
                label="Recording w/o txn (suspicious)"
                value={statNum(stats, "recording_no_txn_suspicious")}
                detail={
                  statNum(stats, "recording_no_txn_suspicious_instructions") > 0
                    ? `${statNum(stats, "recording_no_txn_suspicious_instructions")} unmatched instructions`
                    : undefined
                }
                tone="text-orange-600 dark:text-orange-400"
                onClick={() => goBucket("recording_no_txn", "", "suspicious")}
              />
              <StatTile
                label="Recording w/o txn (info)"
                value={statNum(stats, "recording_no_txn_info")}
                onClick={() => goBucket("recording_no_txn", "", "info")}
              />
              <StatTile
                label="Decisions carried forward"
                value={statNum(stats, "decisions_carried_forward")}
                tone="text-violet-600 dark:text-violet-400"
              />
              <StatTile label="Excluded (channel)" value={statNum(stats, "txns_excluded_channel")} />
            </div>
          )}

          <Card className="overflow-hidden">
            <div className="flex items-center justify-between gap-4 border-b px-4">
              <div role="tablist" aria-label="Reconciliation buckets" className="flex">
                {TABS.map((t) => {
                  const active = tab === t.key;
                  const breach = t.key === "txn_no_recording" && statNum(stats, "txn_no_recording") > 0;
                  const suspicious =
                    t.key === "recording_no_txn" &&
                    statNum(stats, "recording_no_txn_suspicious") > 0;
                  return (
                    <button
                      key={t.key}
                      type="button"
                      role="tab"
                      aria-selected={active}
                      onClick={() => goBucket(t.key)}
                      className={cn(
                        "-mb-px border-b-2 px-4 py-3 text-sm font-medium transition-colors",
                        active
                          ? "border-primary text-foreground"
                          : "border-transparent text-muted-foreground hover:text-foreground",
                      )}
                    >
                      <span className="flex items-center gap-1.5">
                        {breach && (
                          <span aria-hidden className="h-2 w-2 rounded-full bg-red-500" />
                        )}
                        {suspicious && (
                          <span aria-hidden className="h-2 w-2 rounded-full bg-amber-500" />
                        )}
                        {t.label}
                        {active && items !== null && (
                          <span className="font-normal text-muted-foreground">({items.total})</span>
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>
              {tab === "matched" && (
                <Select
                  value={matchStatus}
                  onChange={(e) => {
                    setMatchStatus(e.target.value);
                    setPage(1);
                  }}
                  wrapperClassName="w-44 shrink-0 py-2"
                  className="h-8"
                  aria-label="Filter by match status"
                >
                  <option value="">All statuses</option>
                  {MATCH_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s.replaceAll("_", " ")}
                    </option>
                  ))}
                </Select>
              )}
              {tab === "txn_no_recording" && (
                <Select
                  value={unmatchedReason}
                  onChange={(e) => {
                    setUnmatchedReason(e.target.value);
                    setPage(1);
                  }}
                  wrapperClassName="w-64 shrink-0 py-2"
                  className="h-8"
                  aria-label="Filter by unmatched reason"
                >
                  <option value="">All unmatched reasons</option>
                  {Object.entries(UNMATCHED_REASONS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </Select>
              )}
              {tab === "recording_no_txn" && (
                <Select
                  value={severity}
                  onChange={(e) => {
                    setSeverity(e.target.value);
                    setPage(1);
                  }}
                  wrapperClassName="w-44 shrink-0 py-2"
                  className="h-8"
                  aria-label="Filter by severity"
                >
                  <option value="">All severities</option>
                  <option value="suspicious">Suspicious</option>
                  <option value="info">Info</option>
                </Select>
              )}
            </div>

            {selected.status === "running" ? (
              <p className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Reconciliation in progress — items appear when it completes.
              </p>
            ) : selected.status === "failed" ? (
              <p className="p-6 text-sm text-muted-foreground">
                This run failed — no items were produced.
              </p>
            ) : itemsError !== null ? (
              <p className="p-6 text-sm text-destructive">Failed to load items: {itemsError}</p>
            ) : items === null ? (
              <p className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
              </p>
            ) : items.items.length === 0 ? (
              <p className="p-6 text-sm text-muted-foreground">Nothing in this bucket.</p>
            ) : (
              <>
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead>Severity</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">Score</TableHead>
                      <TableHead>Trade / instruction</TableHead>
                      <TableHead>Recording</TableHead>
                      <TableHead className="text-center" aria-label="Review note" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.items.map((item) => {
                      const diagnostics = itemDiagnostics(item);
                      return (
                      <TableRow
                        key={item.id}
                        tabIndex={0}
                        onClick={() => setDrawerId(item.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") setDrawerId(item.id);
                        }}
                        className="cursor-pointer focus-visible:bg-muted/50 focus-visible:outline-none"
                      >
                        <TableCell>
                          <SeverityBadge severity={item.severity} />
                        </TableCell>
                        <TableCell>
                          <MatchStatusBadge status={item.match_status} />
                          {diagnostics.reason && (
                            <span className="mt-1 block max-w-48 text-xs text-muted-foreground">
                              {UNMATCHED_REASONS[diagnostics.reason]}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatScore(item.score)}
                        </TableCell>
                        <TableCell>
                          {item.transaction ? (
                            <>
                              <span className="font-mono text-xs">
                                {item.transaction.ext_txn_id ?? item.transaction.id.slice(0, 8)}
                              </span>
                              <span className="block text-xs text-muted-foreground">
                                {[
                                  item.transaction.stock_code,
                                  item.transaction.side,
                                  item.transaction.quantity != null
                                    ? new Intl.NumberFormat("en-US").format(
                                        item.transaction.quantity,
                                      )
                                    : null,
                                ]
                                  .filter(Boolean)
                                  .join(" · ")}
                              </span>
                            </>
                          ) : item.instruction ? (
                            <>
                              <span className="text-xs font-medium tabular-nums">
                                {[
                                  item.instruction.side,
                                  item.instruction.quantity != null
                                    ? new Intl.NumberFormat("en-US").format(item.instruction.quantity)
                                    : null,
                                  item.instruction.stock_code,
                                ]
                                  .filter(Boolean)
                                  .join(" · ")}
                              </span>
                              <span className="block text-xs text-muted-foreground">
                                {item.instruction.client_name_raw ?? "from call"}
                              </span>
                            </>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell className="max-w-[280px]">
                          {item.recording ? (
                            <>
                              <Link
                                href={`/recordings/${item.recording.id}`}
                                onClick={(e) => e.stopPropagation()}
                                className="block truncate text-primary hover:underline"
                                title={item.recording.original_filename}
                              >
                                {item.recording.original_filename}
                              </Link>
                              {diagnostics.conflicts.length > 0 && (
                                <span className="block truncate text-xs text-destructive">
                                  {diagnostics.conflicts.map(conflictLabel).join("; ")}
                                </span>
                              )}
                            </>
                          ) : diagnostics.candidate ? (
                            <>
                              <Link
                                href={`/recordings/${diagnostics.candidate.recording_id}`}
                                onClick={(e) => e.stopPropagation()}
                                className="block truncate text-primary hover:underline"
                                title={diagnostics.candidate.original_filename ?? "Closest recording"}
                              >
                                {diagnostics.candidate.original_filename ?? "Closest recording"}
                              </Link>
                              {diagnostics.conflicts.length > 0 && (
                                <span className="block truncate text-xs text-destructive">
                                  {diagnostics.conflicts.map(conflictLabel).join("; ")}
                                </span>
                              )}
                            </>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell className="text-center">
                          {item.review_note ? (
                            <MessageSquare
                              className="mx-auto h-4 w-4 text-muted-foreground"
                              aria-label="Has review note"
                            />
                          ) : null}
                        </TableCell>
                      </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
                {items.total > ITEMS_PAGE_SIZE && (
                  <div className="flex items-center justify-between border-t px-4 py-3 text-sm">
                    <span className="text-muted-foreground">
                      Page {items.page} of {pageCount} · {items.total} items
                    </span>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={page <= 1}
                        onClick={() => setPage((p) => p - 1)}
                      >
                        Previous
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={page >= pageCount}
                        onClick={() => setPage((p) => p + 1)}
                      >
                        Next
                      </Button>
                    </div>
                  </div>
                )}
              </>
            )}
          </Card>
        </div>
      )}

      {drawerItem !== null && selected !== null && (
        <ReviewDrawer
          key={drawerItem.id}
          item={drawerItem}
          runTradeDate={selected.trade_date_from || selected.trade_date}
          canReview={canManage}
          onClose={() => setDrawerId(null)}
          onUpdated={onItemUpdated}
        />
      )}
    </div>
  );
}
