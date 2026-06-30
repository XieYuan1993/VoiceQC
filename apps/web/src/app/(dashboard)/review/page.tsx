import { LinkedRow } from "@/components/linked-row";
import { Pagination } from "@/components/pagination";
import { ReasonBadge, REVIEW_REASON_LEGEND } from "@/components/reason-badge";
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
import { apiCall, getApiErrorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { getActiveProject } from "@/lib/project";
import { scoreTextClass } from "@/lib/score";
import type { ReviewQueue } from "@/lib/types";
import { cn } from "@/lib/utils";

import { cookieHeader } from "../_data";
import { ReviewFilters } from "./filters";

const PAGE_SIZE = 25;
const SORTS = ["score", "recent", "severity"];

function first(v: string | string[] | undefined): string {
  return (Array.isArray(v) ? v[0] : v) ?? "";
}

export default async function ReviewPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const reason = first(sp.reason);
  const agent = first(sp.broker_ext);
  const callDate = first(sp.call_date);
  const sortRaw = first(sp.sort);
  const sort = SORTS.includes(sortRaw) ? sortRaw : "score";
  const page = Math.max(1, Number(first(sp.page)) || 1);

  const cookie = await cookieHeader();
  const { id: projectId } = await getActiveProject(cookie);

  let data: ReviewQueue | null = null;
  let error: string | null = null;
  try {
    data = await apiCall("/api/insights/review-queue", "get", {
      cookieHeader: cookie,
      params: {
        query: {
          project_id: projectId || undefined,
          reason: reason || undefined,
          broker_ext: agent || undefined,
          call_date: callDate || undefined,
          sort,
          page,
          page_size: PAGE_SIZE,
        },
      },
    });
  } catch (e) {
    error = getApiErrorMessage(e);
  }

  let agentOptions: string[] = [];
  try {
    const ag = await apiCall("/api/insights/agents", "get", {
      cookieHeader: cookie,
      params: { query: { project_id: projectId || undefined } },
    });
    agentOptions = (ag?.agents ?? []).map((a) => a.agent);
  } catch {
    agentOptions = [];
  }

  const items = data?.items ?? [];
  const counts = data?.counts;

  const makeHref = (p: number) => {
    const params = new URLSearchParams();
    if (reason) params.set("reason", reason);
    if (agent) params.set("broker_ext", agent);
    if (callDate) params.set("call_date", callDate);
    if (sort && sort !== "score") params.set("sort", sort);
    if (p > 1) params.set("page", String(p));
    const qs = params.toString();
    return qs ? `/review?${qs}` : "/review";
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Review queue</h1>
        <p className="text-sm text-muted-foreground">
          Calls flagged by their latest evaluation — a complaint, an answer the knowledge base
          contradicts, a critical risk flag, or weak script adherence. Filter by reason, agent or
          date.
        </p>
      </div>

      <ReviewFilters
        key={`${reason}|${agent}|${callDate}|${sort}`}
        reason={reason}
        agent={agent}
        callDate={callDate}
        sort={sort}
        counts={counts}
        agents={agentOptions}
      />

      <StatusLegend items={REVIEW_REASON_LEGEND} label="What does each reason mean?" />

      {error !== null ? (
        <Card>
          <CardContent className="p-6 text-sm text-destructive">Failed to load: {error}</CardContent>
        </Card>
      ) : data === null || items.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            {reason || agent || callDate
              ? "No flagged calls match these filters."
              : "Nothing needs attention — no flagged calls in this project. 🎉"}
          </CardContent>
        </Card>
      ) : (
        <>
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Agent</TableHead>
                  <TableHead>Recording</TableHead>
                  <TableHead>Why flagged</TableHead>
                  <TableHead className="text-right">Score</TableHead>
                  <TableHead>Call time</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((r) => (
                  <LinkedRow key={r.recording_id} href={`/recordings/${r.recording_id}`}>
                    <TableCell className="font-medium tabular-nums">{r.broker_ext ?? "—"}</TableCell>
                    <TableCell className="max-w-[280px]">
                      <span className="block truncate" title={r.original_filename}>
                        {r.original_filename}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {r.reasons.map((x) => (
                          <ReasonBadge key={x} reason={x} />
                        ))}
                      </div>
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
                    <TableCell>
                      <StatusBadge status={r.status} />
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
