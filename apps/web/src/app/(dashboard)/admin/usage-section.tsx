"use client";

import { Loader2, Trash2, TriangleAlert } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiCall, getApiErrorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { Usage, UsageDay } from "@/lib/types";

// ---- helpers -------------------------------------------------------------

function num(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

/** Sum a set of UsageDay rows into a per-day total of the chosen metric. */
function byDay(rows: UsageDay[], metric: (r: UsageDay) => number): Map<string, number> {
  const out = new Map<string, number>();
  for (const r of rows) {
    out.set(r.day, (out.get(r.day) ?? 0) + metric(r));
  }
  return out;
}

function compactInt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return String(Math.round(n));
}

/** Inline SVG bar chart — one bar per day, no chart lib. */
function BarChart({
  series,
  budget,
  format,
  emptyLabel,
}: {
  series: { day: string; value: number }[];
  budget: number;
  format: (n: number) => string;
  emptyLabel: string;
}) {
  if (series.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  }
  const max = Math.max(budget > 0 ? budget : 0, ...series.map((s) => s.value), 1);
  const W = 640;
  const H = 120;
  const gap = 2;
  const barW = Math.max(1, (W - gap * (series.length - 1)) / series.length);
  // Budget line position (from the top).
  const budgetY = budget > 0 ? H - (budget / max) * H : null;

  return (
    <div className="space-y-1">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-32 w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label="Daily usage bars"
      >
        {series.map((s, i) => {
          const h = (s.value / max) * H;
          const over = budget > 0 && s.value > budget;
          return (
            <rect
              key={s.day}
              x={i * (barW + gap)}
              y={H - h}
              width={barW}
              height={h}
              rx={1}
              className={over ? "fill-destructive" : "fill-primary"}
            >
              <title>{`${s.day}: ${format(s.value)}`}</title>
            </rect>
          );
        })}
        {budgetY != null && (
          <line
            x1={0}
            x2={W}
            y1={budgetY}
            y2={budgetY}
            className="stroke-amber-500"
            strokeDasharray="4 3"
            strokeWidth={1}
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>
      <div className="flex justify-between text-[11px] text-muted-foreground">
        <span>{series[0].day}</span>
        {budget > 0 && (
          <span className="text-amber-600 dark:text-amber-400">
            budget {format(budget)}/day
          </span>
        )}
        <span>{series[series.length - 1].day}</span>
      </div>
    </div>
  );
}

function TodayStat({
  label,
  value,
  budget,
  format,
}: {
  label: string;
  value: number;
  budget: number;
  format: (n: number) => string;
}) {
  const over = budget > 0 && value > budget;
  const pct = budget > 0 ? Math.round((value / budget) * 100) : null;
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={"text-2xl font-semibold tabular-nums " + (over ? "text-destructive" : "")}>
        {format(value)}
      </p>
      <p className="text-xs text-muted-foreground">
        {budget > 0 ? (
          <>
            of {format(budget)} budget{pct != null ? ` (${pct}%)` : ""}
          </>
        ) : (
          "no budget set"
        )}
      </p>
    </div>
  );
}

// ---- Retention -----------------------------------------------------------

interface RetentionPreview {
  retention_days: number;
  cutoff: string | null;
  recordings_to_purge: number;
  txn_files_to_purge: number;
}

function readPreview(raw: Record<string, unknown>): RetentionPreview {
  return {
    retention_days: num(raw.retention_days),
    cutoff: typeof raw.cutoff === "string" ? raw.cutoff : null,
    recordings_to_purge: num(raw.recordings_to_purge),
    txn_files_to_purge: num(raw.txn_files_to_purge),
  };
}

function RetentionCard() {
  const [preview, setPreview] = React.useState<RetentionPreview | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [confirming, setConfirming] = React.useState(false);
  const [running, setRunning] = React.useState(false);
  const [runError, setRunError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      const raw = await apiCall("/api/admin/retention/preview", "get", {});
      setPreview(readPreview(raw as Record<string, unknown>));
      setLoadError(null);
    } catch (e) {
      setLoadError(getApiErrorMessage(e));
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function onRun() {
    setRunning(true);
    setRunError(null);
    try {
      // 202 Accepted — apiCall returns the parsed body regardless of status.
      const res = (await apiCall("/api/admin/retention/run", "post", {})) as {
        status?: unknown;
      };
      const status = typeof res?.status === "string" ? res.status : "queued";
      setNotice(`Retention sweep ${status}.`);
      setConfirming(false);
      await load();
    } catch (e) {
      setRunError(getApiErrorMessage(e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Data retention</CardTitle>
        <CardDescription>
          Recordings and imported transaction files older than the retention
          window are purged daily. Preview the next sweep below.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {loadError !== null ? (
          <p className="text-sm text-destructive">Failed to load preview: {loadError}</p>
        ) : preview === null ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-4">
              <div>
                <p className="text-xs text-muted-foreground">Retention window</p>
                <p className="text-xl font-semibold tabular-nums">
                  {preview.retention_days} days
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Cutoff</p>
                <p className="text-xl font-semibold tabular-nums">
                  {formatDateTime(preview.cutoff)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Recordings to purge</p>
                <p className="text-xl font-semibold tabular-nums">
                  {preview.recordings_to_purge.toLocaleString()}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Txn files to purge</p>
                <p className="text-xl font-semibold tabular-nums">
                  {preview.txn_files_to_purge.toLocaleString()}
                </p>
              </div>
            </div>
            {notice && (
              <p className="text-sm text-emerald-700 dark:text-emerald-400">{notice}</p>
            )}
            <Button variant="destructive" size="sm" onClick={() => setConfirming(true)}>
              <Trash2 className="mr-2 h-4 w-4" aria-hidden />
              Run now
            </Button>
          </>
        )}
      </CardContent>

      {confirming && (
        <Dialog open onOpenChange={(o) => !o && !running && setConfirming(false)}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <TriangleAlert className="h-5 w-5 text-destructive" aria-hidden />
                Run retention sweep now?
              </DialogTitle>
              <DialogDescription>
                This permanently deletes{" "}
                {preview ? (
                  <>
                    <strong>{preview.recordings_to_purge.toLocaleString()}</strong>{" "}
                    recording(s) and{" "}
                    <strong>{preview.txn_files_to_purge.toLocaleString()}</strong>{" "}
                    transaction file(s)
                  </>
                ) : (
                  "all data"
                )}{" "}
                older than the retention window. This cannot be undone.
              </DialogDescription>
            </DialogHeader>
            {runError && <p className="text-sm text-destructive">{runError}</p>}
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setConfirming(false)}
                disabled={running}
              >
                Cancel
              </Button>
              <Button variant="destructive" onClick={onRun} disabled={running}>
                {running && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
                Run sweep
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </Card>
  );
}

// ---- Section -------------------------------------------------------------

export function UsageSection() {
  const [usage, setUsage] = React.useState<Usage | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    apiCall("/api/admin/usage", "get", { params: { query: { days: 30 } } })
      .then((u) => {
        if (!cancelled) setUsage(u);
      })
      .catch((e) => {
        if (!cancelled) setLoadError(getApiErrorMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const llmSeries = React.useMemo(() => {
    if (!usage) return [];
    const m = byDay(usage.llm, (r) => num(r.input_tokens) + num(r.output_tokens));
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([day, value]) => ({ day, value }));
  }, [usage]);

  const sttSeries = React.useMemo(() => {
    if (!usage) return [];
    const m = byDay(usage.stt, (r) => num(r.audio_seconds));
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([day, value]) => ({ day, value }));
  }, [usage]);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Model usage</CardTitle>
          <CardDescription>
            LLM tokens and speech-to-text seconds per day (last 30 days), against
            the configured daily budgets.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-8">
          {loadError !== null ? (
            <p className="text-sm text-destructive">Failed to load usage: {loadError}</p>
          ) : usage === null ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
            </p>
          ) : (
            <>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium">LLM tokens</h3>
                  <TodayStat
                    label="Today"
                    value={usage.llm_today_tokens}
                    budget={usage.llm_daily_budget}
                    format={compactInt}
                  />
                </div>
                <BarChart
                  series={llmSeries}
                  budget={usage.llm_daily_budget}
                  format={compactInt}
                  emptyLabel="No LLM usage recorded."
                />
              </div>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium">Speech-to-text seconds</h3>
                  <TodayStat
                    label="Today"
                    value={usage.stt_today_seconds}
                    budget={usage.stt_daily_budget}
                    format={(n) => `${compactInt(n)}s`}
                  />
                </div>
                <BarChart
                  series={sttSeries}
                  budget={usage.stt_daily_budget}
                  format={(n) => `${compactInt(n)}s`}
                  emptyLabel="No STT usage recorded."
                />
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <RetentionCard />
    </div>
  );
}
