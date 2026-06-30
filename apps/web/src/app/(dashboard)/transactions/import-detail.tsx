"use client";

import { AlertTriangle, Loader2, Trash2 } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
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
import type { SkippedRow, TxnImport } from "@/lib/types";

const REASON_LABEL: Record<string, string> = {
  duplicate: "Duplicate fill of an order already imported",
  side: "Unrecognized buy/sell value",
  status: "Filtered out by order status",
};

function num(n: number | null | undefined): string {
  return n == null ? "—" : new Intl.NumberFormat("en-US").format(n);
}

export function ImportDetail({
  imp,
  canManage,
  onClose,
  onDeleted,
}: {
  imp: TxnImport;
  canManage: boolean;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [skipped, setSkipped] = React.useState<SkippedRow[] | null>(null);
  const [skippedError, setSkippedError] = React.useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (imp.skipped_count === 0) {
      setSkipped([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const rows = await apiCall("/api/txn-imports/{import_id}/skipped", "get", {
          params: { path: { import_id: imp.id } },
        });
        if (!cancelled) setSkipped(rows);
      } catch (e) {
        if (!cancelled) setSkippedError(getApiErrorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [imp.id, imp.skipped_count]);

  async function onDelete() {
    setDeleting(true);
    setError(null);
    try {
      await apiCall("/api/txn-imports/{import_id}", "delete", {
        params: { path: { import_id: imp.id } },
      });
      onDeleted();
    } catch (e) {
      setError(getApiErrorMessage(e));
      setDeleting(false);
    }
  }

  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle className="flex flex-wrap items-center gap-2">
            Import detail
            <StatusBadge status={imp.status} />
          </SheetTitle>
        </SheetHeader>

        <div className="space-y-1 text-sm">
          <p className="font-medium">{imp.file_name ?? "—"}</p>
          <p className="text-muted-foreground">
            Trade date {imp.trade_date} · {imp.kind === "api_pull" ? "API pull" : "CSV upload"} ·{" "}
            {formatDateTime(imp.created_at)}
          </p>
        </div>

        <dl className="grid grid-cols-3 gap-3 rounded-md border p-3 text-sm">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Rows</dt>
            <dd className="mt-0.5 text-lg font-semibold tabular-nums">{imp.row_count}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Imported</dt>
            <dd className="mt-0.5 text-lg font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
              {imp.imported_count}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Skipped</dt>
            <dd className="mt-0.5 text-lg font-semibold tabular-nums text-amber-600 dark:text-amber-400">
              {imp.skipped_count}
            </dd>
          </div>
        </dl>

        {imp.imported_count > 0 && (
          <Link
            href={`/transactions?import_id=${imp.id}`}
            onClick={onClose}
            className="inline-flex text-sm font-medium text-primary hover:underline"
          >
            View {imp.imported_count} imported transaction{imp.imported_count === 1 ? "" : "s"} →
          </Link>
        )}

        <div>
          <h3 className="mb-1 text-sm font-medium">Errors</h3>
          {imp.errors.length === 0 ? (
            <p className="text-sm text-muted-foreground">No errors.</p>
          ) : (
            <ul className="space-y-1 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
              {imp.errors.map((e, i) => (
                <li key={i}>{typeof e === "string" ? e : JSON.stringify(e)}</li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h3 className="mb-1 text-sm font-medium">
            Skipped rows{imp.skipped_count > 0 ? ` (${imp.skipped_count})` : ""}
          </h3>
          {imp.skipped_count === 0 ? (
            <p className="text-sm text-muted-foreground">None — every data row was imported.</p>
          ) : skippedError !== null ? (
            <p className="text-sm text-destructive">{skippedError}</p>
          ) : skipped === null ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
            </p>
          ) : (
            <div className="max-h-64 overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Ext ref</TableHead>
                    <TableHead>Stock</TableHead>
                    <TableHead>Side</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead>Reason</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {skipped.map((r, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-mono text-xs">{r.ext_txn_id ?? "—"}</TableCell>
                      <TableCell className="tabular-nums">{r.stock_code ?? "—"}</TableCell>
                      <TableCell>{r.side ?? "—"}</TableCell>
                      <TableCell className="text-right tabular-nums">{num(r.quantity)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {REASON_LABEL[r.reason] ?? r.reason}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>

        {canManage && (
          <div className="space-y-2 border-t pt-4">
            {error && <p className="text-sm text-destructive">{error}</p>}
            {confirmDelete ? (
              <div className="space-y-2 rounded-md border border-destructive/40 bg-destructive/5 p-3">
                <p className="flex items-start gap-2 text-sm">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
                  Delete this import and its {imp.imported_count} transaction
                  {imp.imported_count === 1 ? "" : "s"}? Reconciliation re-runs for the affected
                  dates.
                </p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={deleting}
                    onClick={() => void onDelete()}
                  >
                    {deleting ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                    ) : (
                      <Trash2 className="mr-2 h-4 w-4" aria-hidden />
                    )}
                    Delete import
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={deleting}
                    onClick={() => setConfirmDelete(false)}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <Button
                size="sm"
                variant="outline"
                className="text-destructive hover:text-destructive"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="mr-2 h-4 w-4" aria-hidden />
                Delete import
              </Button>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
