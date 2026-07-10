"use client";

import { Download, Loader2, MessageSquare, Play, RefreshCw } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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

const ORDER_STATUS_OPTIONS = [
  "已委託",
  "成交",
  "部分成交",
  "已過期",
  "待報",
  "已撤單",
  "待報（保價）",
  "已修改",
  "待報（條件單）",
  "已拒絕",
];

const EXECUTION_TYPE_OPTIONS = [
  "",
  "TradeExec",
  "NewExec",
  "ExpiredExec",
  "ReplaceExec",
  "CanceledExec",
];

interface RunFilters {
  order_statuses: string[];
  execution_types: string[];
}

interface RunRange {
  from: string;
  to: string;
}

const DEFAULT_RUN_FILTERS: RunFilters = {
  order_statuses: ORDER_STATUS_OPTIONS,
  execution_types: EXECUTION_TYPE_OPTIONS,
};

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
  tone,
  onClick,
}: {
  label: string;
  value: number;
  tone?: string;
  onClick?: () => void;
}) {
  const inner = (
    <>
      <p className={cn("text-2xl font-semibold tabular-nums", tone)}>{value}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
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

function toggleValue(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

function RunFiltersDialog({
  range,
  pending,
  onCancel,
  onConfirm,
}: {
  range: RunRange;
  pending: boolean;
  onCancel: () => void;
  onConfirm: (filters: RunFilters) => void;
}) {
  const [orderStatuses, setOrderStatuses] = React.useState<string[]>(
    DEFAULT_RUN_FILTERS.order_statuses,
  );
  const [executionTypes, setExecutionTypes] = React.useState<string[]>(
    DEFAULT_RUN_FILTERS.execution_types,
  );

  return (
    <Dialog open onOpenChange={(open) => !open && !pending && onCancel()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Run reconciliation</DialogTitle>
          <DialogDescription>
            Select which imported transaction rows participate in matching for{" "}
            {range.from === range.to ? range.from : `${range.from} - ${range.to}`}.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label>訂單狀態</Label>
              <Button
                type="button"
                variant="ghost"
                className="h-auto px-1 py-0.5 text-xs"
                onClick={() =>
                  setOrderStatuses(
                    orderStatuses.length === ORDER_STATUS_OPTIONS.length ? [] : ORDER_STATUS_OPTIONS,
                  )
                }
              >
                {orderStatuses.length === ORDER_STATUS_OPTIONS.length ? "Clear" : "All"}
              </Button>
            </div>
            <div className="max-h-64 space-y-1.5 overflow-auto rounded-md border p-3">
              {ORDER_STATUS_OPTIONS.map((value) => (
                <label key={value} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={orderStatuses.includes(value)}
                    onChange={() => setOrderStatuses((prev) => toggleValue(prev, value))}
                    className="h-4 w-4 rounded border-input"
                  />
                  <span>{value}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label>執行類型</Label>
              <Button
                type="button"
                variant="ghost"
                className="h-auto px-1 py-0.5 text-xs"
                onClick={() =>
                  setExecutionTypes(
                    executionTypes.length === EXECUTION_TYPE_OPTIONS.length
                      ? []
                      : EXECUTION_TYPE_OPTIONS,
                  )
                }
              >
                {executionTypes.length === EXECUTION_TYPE_OPTIONS.length ? "Clear" : "All"}
              </Button>
            </div>
            <div className="max-h-64 space-y-1.5 overflow-auto rounded-md border p-3">
              {EXECUTION_TYPE_OPTIONS.map((value) => (
                <label key={value || "__blank"} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={executionTypes.includes(value)}
                    onChange={() => setExecutionTypes((prev) => toggleValue(prev, value))}
                    className="h-4 w-4 rounded border-input"
                  />
                  <span>{value || "(blank)"}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={pending || orderStatuses.length === 0 || executionTypes.length === 0}
            onClick={() =>
              onConfirm({
                order_statuses: orderStatuses,
                execution_types: executionTypes,
              })
            }
          >
            {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
            Run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ReconView({ canManage }: { canManage: boolean }) {
  const [runs, setRuns] = React.useState<ReconRun[] | null>(null);
  const [runsError, setRunsError] = React.useState<string | null>(null);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const [tradeDateFrom, setTradeDateFrom] = React.useState(todayISO());
  const [tradeDateTo, setTradeDateTo] = React.useState(todayISO());
  const [creating, setCreating] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [pendingRunRange, setPendingRunRange] = React.useState<RunRange | null>(null);

  const [tab, setTab] = React.useState<Bucket>("matched");
  const [page, setPage] = React.useState(1);
  const [matchStatus, setMatchStatus] = React.useState("");
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

  const goBucket = React.useCallback((b: Bucket, status = "") => {
    setTab(b);
    setMatchStatus(status);
    setPage(1);
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
    setDrawerId(null);
  }, [selectedId, tab]);

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
  }, [selectedId, tab, page, matchStatus]);

  React.useEffect(() => {
    setItems(null);
    setItemsError(null);
    if (selectedId === null || selectedStatus !== "completed") return;
    void loadItems();
  }, [loadItems, selectedId, selectedStatus]);

  async function runFor(range: RunRange, filters: RunFilters) {
    if (!range.from || !range.to) return;
    setCreating(true);
    setActionError(null);
    try {
      const run = await apiCall("/api/recon/runs", "post", {
        body: {
          trade_date_from: range.from,
          trade_date_to: range.to,
          transaction_filters: filters,
        },
      });
      setSelectedId(run.id);
      setPendingRunRange(null);
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
    setPendingRunRange({ from: tradeDateFrom, to: tradeDateTo });
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
                  setPendingRunRange({
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
                tone="text-orange-600 dark:text-orange-400"
                onClick={() => goBucket("recording_no_txn")}
              />
              <StatTile
                label="Recording w/o txn (info)"
                value={statNum(stats, "recording_no_txn_info")}
                onClick={() => goBucket("recording_no_txn")}
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
                      onClick={() => setTab(t.key)}
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
                    {items.items.map((item) => (
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
                            <Link
                              href={`/recordings/${item.recording.id}`}
                              onClick={(e) => e.stopPropagation()}
                              className="block truncate text-primary hover:underline"
                              title={item.recording.original_filename}
                            >
                              {item.recording.original_filename}
                            </Link>
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
                    ))}
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

      {pendingRunRange !== null && (
        <RunFiltersDialog
          range={pendingRunRange}
          pending={creating}
          onCancel={() => setPendingRunRange(null)}
          onConfirm={(filters) => void runFor(pendingRunRange, filters)}
        />
      )}
    </div>
  );
}
