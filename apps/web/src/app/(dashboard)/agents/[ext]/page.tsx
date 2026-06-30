import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { LinkedRow } from "@/components/linked-row";
import { Pagination } from "@/components/pagination";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiCall, getApiErrorMessage } from "@/lib/api";
import { formatDateTime, formatDuration } from "@/lib/format";
import { getActiveProject } from "@/lib/project";
import { bandToRange, scoreBgClass, scoreTextClass } from "@/lib/score";
import type { AgentDetail, RecordingList } from "@/lib/types";
import { cn } from "@/lib/utils";

import { cookieHeader } from "../../_data";
import { AgentCallsFilters } from "./calls-filters";

const PAGE_SIZE = 25;

function first(v: string | string[] | undefined): string {
  return (Array.isArray(v) ? v[0] : v) ?? "";
}

function StatCard({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={cn("mt-1 text-2xl font-semibold tabular-nums", tone)}>{value}</p>
      </CardContent>
    </Card>
  );
}

export default async function AgentDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ ext: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { ext } = await params;
  const sp = await searchParams;
  const status = first(sp.status);
  const callDate = first(sp.call_date);
  const band = first(sp.band);
  const page = Math.max(1, Number(first(sp.page)) || 1);

  const cookie = await cookieHeader();
  const { id: projectId } = await getActiveProject(cookie);
  const { min, max } = bandToRange(band);

  let detail: AgentDetail | null = null;
  let detailError: string | null = null;
  try {
    detail = await apiCall("/api/insights/agents/{broker_ext}", "get", {
      cookieHeader: cookie,
      params: { path: { broker_ext: ext }, query: { project_id: projectId || undefined } },
    });
  } catch (e) {
    detailError = getApiErrorMessage(e);
  }

  let calls: RecordingList | null = null;
  try {
    calls = await apiCall("/api/recordings", "get", {
      cookieHeader: cookie,
      params: {
        query: {
          project_id: projectId || undefined,
          broker_ext: ext,
          status: status || undefined,
          call_date: callDate || undefined,
          min_score: min,
          max_score: max,
          page,
          page_size: PAGE_SIZE,
        },
      },
    });
  } catch {
    calls = null;
  }

  const makeHref = (p: number) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (callDate) params.set("call_date", callDate);
    if (band) params.set("band", band);
    if (p > 1) params.set("page", String(p));
    const qs = params.toString();
    const base = `/agents/${encodeURIComponent(ext)}`;
    return qs ? `${base}?${qs}` : base;
  };

  const trend = detail?.trend ?? [];
  const showTrend = trend.filter((t) => t.avg_score != null).length >= 2;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/agents"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden /> All agents
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tabular-nums">
          Agent {ext}
          {detail?.name && (
            <span className="ml-2 text-lg font-normal text-muted-foreground">{detail.name}</span>
          )}
        </h1>
        <p className="text-sm text-muted-foreground">Scorecard and calls for this agent.</p>
      </div>

      {detailError ? (
        <Card>
          <CardContent className="p-6 text-sm text-destructive">
            Failed to load agent: {detailError}
          </CardContent>
        </Card>
      ) : detail ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Calls evaluated" value={detail.calls} />
            <StatCard
              label="Avg score"
              value={detail.avg_score != null ? Math.round(detail.avg_score) : "—"}
              tone={scoreTextClass(detail.avg_score)}
            />
            <StatCard
              label="Adherence"
              value={detail.avg_adherence != null ? `${Math.round(detail.avg_adherence)}%` : "—"}
              tone={scoreTextClass(detail.avg_adherence)}
            />
            <StatCard
              label="Answer accuracy"
              value={detail.avg_correctness != null ? `${Math.round(detail.avg_correctness)}%` : "—"}
              tone={scoreTextClass(detail.avg_correctness)}
            />
          </div>
          <p className="text-sm text-muted-foreground">
            Complaints {Math.round(detail.complaint_rate * 100)}% · Wrong answers{" "}
            {detail.incorrect_answer_calls}
          </p>

          <Card>
            <CardContent className="space-y-3 p-5">
              <h2 className="text-sm font-medium text-muted-foreground">Daily average score</h2>
              {showTrend ? (
                <div className="flex items-end gap-1" style={{ height: 110 }}>
                  {trend.map((t) => (
                    <div
                      key={t.date}
                      className="flex flex-1 flex-col items-center gap-1"
                      title={`${t.date}: ${t.avg_score != null ? Math.round(t.avg_score) : "—"} · ${t.calls} call(s)`}
                    >
                      <div className="flex w-full items-end justify-center" style={{ height: 88 }}>
                        <div
                          className={cn("w-full max-w-[22px] rounded-t", scoreBgClass(t.avg_score))}
                          style={{ height: `${Math.max(3, t.avg_score ?? 0)}%` }}
                        />
                      </div>
                      {trend.length <= 20 && (
                        <span className="text-[9px] tabular-nums text-muted-foreground">
                          {t.date.slice(5)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Not enough call history yet to chart a trend.
                </p>
              )}
            </CardContent>
          </Card>
        </>
      ) : null}

      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Calls</h2>
          <AgentCallsFilters ext={ext} status={status} callDate={callDate} band={band} />
        </div>
        {calls === null || calls.items.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              No calls match{status || callDate || band ? " these filters." : " for this agent."}
            </CardContent>
          </Card>
        ) : (
          <>
            <Card className="overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Filename</TableHead>
                    <TableHead className="text-right">Score</TableHead>
                    <TableHead>Call time</TableHead>
                    <TableHead className="text-right">Duration</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {calls.items.map((r) => (
                    <LinkedRow key={r.id} href={`/recordings/${r.id}`}>
                      <TableCell className="max-w-[360px]">
                        <span className="block truncate font-medium" title={r.original_filename}>
                          {r.original_filename}
                        </span>
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-right font-medium tabular-nums",
                          scoreTextClass(r.overall_score),
                        )}
                      >
                        {r.overall_score != null ? Math.round(r.overall_score) : "—"}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        {formatDateTime(r.call_started_at)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatDuration(r.duration_seconds)}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={r.status} />
                      </TableCell>
                    </LinkedRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
            <Pagination
              page={calls.page}
              pageSize={calls.page_size}
              total={calls.total}
              makeHref={makeHref}
            />
          </>
        )}
      </div>
    </div>
  );
}
