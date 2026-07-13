import Link from "next/link";

import { auth } from "@/auth";
import { DeleteBatchButton } from "@/components/delete-batch-button";
import { Pagination } from "@/components/pagination";
import { StageChips, StatusBadge } from "@/components/status-badge";
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
import { canManage } from "@/lib/roles";
import type { Batch, BatchList } from "@/lib/types";

import { cookieHeader } from "../_data";
import { BatchFilters } from "./filters";
import { BulkBatchActions } from "./bulk-batch-actions";
import { NewBatchButton } from "./new-batch-button";

const PAGE_SIZE = 20;

function first(v: string | string[] | undefined): string {
  return (Array.isArray(v) ? v[0] : v) ?? "";
}

function fileCount(b: Batch): number {
  const c = b.counts;
  const sum = c
    ? c.uploaded + c.converting + c.transcribing + c.evaluating + c.completed + c.failed
    : 0;
  // total_files is only set once the batch is finalized and expanded; before
  // that the recording rows (counts) are the truth.
  return Math.max(b.total_files, sum);
}

export default async function BatchesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const status = first(sp.status);
  const q = first(sp.q);
  const from = first(sp.from);
  const to = first(sp.to);
  const page = Math.max(1, Number(first(sp.page)) || 1);

  const session = await auth();
  const manage = canManage(session?.user?.role);

  const cookie = await cookieHeader();
  const { id: projectId } = await getActiveProject(cookie);

  let data: BatchList | null = null;
  let error: string | null = null;
  try {
    data = await apiCall("/api/batches", "get", {
      cookieHeader: cookie,
      params: {
        query: {
          project_id: projectId || undefined,
          status: status || undefined,
          q: q || undefined,
          call_date_from: from || undefined,
          call_date_to: to || undefined,
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
    if (q) params.set("q", q);
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    if (p > 1) params.set("page", String(p));
    const qs = params.toString();
    return qs ? `/batches?${qs}` : "/batches";
  };

  const hasFilters = Boolean(status || q || from || to);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Batches</h1>
          <p className="text-sm text-muted-foreground">
            Recording upload batches and processing runs.
          </p>
        </div>
        {manage && (
          <div className="flex items-start gap-2">
            <BulkBatchActions />
            <NewBatchButton />
          </div>
        )}
      </div>

      <BatchFilters key={`${status}|${q}|${from}|${to}`} status={status} q={q} from={from} to={to} />

      {error !== null ? (
        <Card>
          <CardContent className="p-6 text-sm text-destructive">
            Failed to load batches: {error}
          </CardContent>
        </Card>
      ) : data === null || data.items.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            {hasFilters
              ? "No batches match these filters."
              : manage
                ? "No batches yet — create one to start uploading recordings."
                : "No batches yet."}
          </CardContent>
        </Card>
      ) : (
        <>
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Name</TableHead>
                  <TableHead>Batch date</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Files</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Last run</TableHead>
                  <TableHead>Created</TableHead>
                  {manage && <TableHead className="w-10" aria-label="Actions" />}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell>
                      <Link
                        href={`/batches/${b.id}`}
                        className="font-medium text-primary hover:underline"
                      >
                        {b.name ?? b.trade_date}
                      </Link>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{b.trade_date}</TableCell>
                    <TableCell>
                      <StatusBadge status={b.status} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{fileCount(b)}</TableCell>
                    <TableCell>
                      <StageChips counts={b.counts} hideZero />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {b.last_run_at ? formatDateTime(b.last_run_at) : "-"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {formatDateTime(b.created_at)}
                    </TableCell>
                    {manage && (
                      <TableCell className="text-right">
                        <DeleteBatchButton
                          batchId={b.id}
                          batchName={b.name ?? String(b.trade_date)}
                          fileCount={fileCount(b)}
                        />
                      </TableCell>
                    )}
                  </TableRow>
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
