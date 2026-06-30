import { LinkedRow } from "@/components/linked-row";
import { Pagination } from "@/components/pagination";
import { StatusBadge } from "@/components/status-badge";
import { StatusLegend } from "@/components/status-legend";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { auth } from "@/auth";
import { apiCall, getApiErrorMessage } from "@/lib/api";
import { formatDateTime, formatDuration } from "@/lib/format";
import { getActiveProject } from "@/lib/project";
import { canManage } from "@/lib/roles";
import { RECORDING_STATUS_LEGEND } from "@/lib/status-meta";
import type { RecordingList } from "@/lib/types";
import { cn } from "@/lib/utils";

import { cookieHeader } from "../_data";
import { RecordingActions } from "./actions";
import { RecordingFilters } from "./filters";

const PAGE_SIZE = 25;

function first(v: string | string[] | undefined): string {
  return (Array.isArray(v) ? v[0] : v) ?? "";
}

export default async function RecordingsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const status = first(sp.status);
  const callDate = first(sp.call_date);
  const q = first(sp.q);
  const page = Math.max(1, Number(first(sp.page)) || 1);

  const cookie = await cookieHeader();
  const { id: projectId } = await getActiveProject(cookie);
  const session = await auth();
  const manage = canManage(session?.user?.role);

  let data: RecordingList | null = null;
  let error: string | null = null;
  try {
    data = await apiCall("/api/recordings", "get", {
      cookieHeader: cookie,
      params: {
        query: {
          project_id: projectId || undefined,
          status: status || undefined,
          call_date: callDate || undefined,
          q: q || undefined,
          page,
          page_size: PAGE_SIZE,
        },
      },
    });
  } catch (e) {
    error = getApiErrorMessage(e);
  }

  const makeHref = (p: number) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (callDate) params.set("call_date", callDate);
    if (q) params.set("q", q);
    if (p > 1) params.set("page", String(p));
    const qs = params.toString();
    return qs ? `/recordings?${qs}` : "/recordings";
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Recordings</h1>
          <p className="text-sm text-muted-foreground">
            Browse calls across all batches; click a row for audio and transcript.
          </p>
        </div>
        <RecordingActions projectId={projectId || ""} status={status} q={q} canManage={manage} />
      </div>

      <RecordingFilters
        key={`${status}|${callDate}|${q}`}
        status={status}
        callDate={callDate}
        q={q}
      />

      <StatusLegend items={RECORDING_STATUS_LEGEND} label="What do the statuses mean?" />

      {error !== null ? (
        <Card>
          <CardContent className="p-6 text-sm text-destructive">
            Failed to load recordings: {error}
          </CardContent>
        </Card>
      ) : data === null || data.items.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            No recordings match{status || callDate || q ? " these filters." : " — upload a batch first."}
          </CardContent>
        </Card>
      ) : (
        <>
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Filename</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>Direction</TableHead>
                  <TableHead>Call time</TableHead>
                  <TableHead className="text-right">Duration</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-center">Transcript</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((r) => (
                  <LinkedRow key={r.id} href={`/recordings/${r.id}`}>
                    <TableCell className="max-w-[320px]">
                      <span className="block truncate font-medium" title={r.original_filename}>
                        {r.original_filename}
                      </span>
                    </TableCell>
                    <TableCell>{r.broker_ext ?? "—"}</TableCell>
                    <TableCell className="capitalize">{r.direction}</TableCell>
                    <TableCell className="whitespace-nowrap">
                      {formatDateTime(r.call_started_at)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatDuration(r.duration_seconds)}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={r.status} />
                    </TableCell>
                    <TableCell className="text-center">
                      <span
                        title={r.has_transcript ? "Transcript available" : "No transcript yet"}
                        className={cn(
                          "mx-auto block h-2.5 w-2.5 rounded-full",
                          r.has_transcript
                            ? "bg-emerald-500"
                            : "border border-muted-foreground/40 bg-transparent",
                        )}
                      />
                      <span className="sr-only">
                        {r.has_transcript ? "Transcript available" : "No transcript yet"}
                      </span>
                    </TableCell>
                  </LinkedRow>
                ))}
              </TableBody>
            </Table>
          </Card>
          <Pagination
            page={data.page}
            pageSize={data.page_size}
            total={data.total}
            makeHref={makeHref}
          />
        </>
      )}
    </div>
  );
}
