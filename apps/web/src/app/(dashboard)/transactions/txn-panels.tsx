"use client";

import { Loader2, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import type { TxnImport, TxnSource } from "@/lib/types";

import { ImportDetail } from "./import-detail";
import { ImportWizard } from "./import-wizard";
import { SourcesSection } from "./sources-section";

const POLL_MS = 5000;
const COLLAPSED_IMPORT_ROWS = 10;

function isInFlight(i: TxnImport): boolean {
  return i.status === "pending" || i.status === "processing";
}

const KIND_LABEL: Record<string, string> = {
  csv_upload: "CSV upload",
  api_pull: "API pull",
};

/**
 * Client island under the server-rendered transactions table: imports history
 * (+ import wizard) and source configs. One parent so a "Pull now" from the
 * sources card shows up in the imports card immediately.
 */
export function TxnPanels({ canManage }: { canManage: boolean }) {
  const router = useRouter();
  const [imports, setImports] = React.useState<TxnImport[] | null>(null);
  const [importsError, setImportsError] = React.useState<string | null>(null);
  const [sources, setSources] = React.useState<TxnSource[] | null>(null);
  const [sourcesError, setSourcesError] = React.useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = React.useState(false);
  const [showAllImports, setShowAllImports] = React.useState(false);
  const [detailImport, setDetailImport] = React.useState<TxnImport | null>(null);

  const importsRef = React.useRef<TxnImport[] | null>(null);

  const loadImports = React.useCallback(async () => {
    try {
      const list = await apiCall("/api/txn-imports", "get");
      // When the last in-flight import settles, the transactions table
      // (server-rendered above) is stale — refresh the route once.
      const before = importsRef.current?.some(isInFlight) ?? false;
      const after = list.some(isInFlight);
      importsRef.current = list;
      setImports(list);
      setImportsError(null);
      if (before && !after) router.refresh();
    } catch (e) {
      if (importsRef.current === null) setImportsError(getApiErrorMessage(e));
    }
  }, [router]);

  const loadSources = React.useCallback(async () => {
    try {
      const list = await apiCall("/api/txn-sources", "get");
      setSources(list);
      setSourcesError(null);
    } catch (e) {
      setSourcesError(getApiErrorMessage(e));
    }
  }, []);

  React.useEffect(() => {
    void loadImports();
    void loadSources();
  }, [loadImports, loadSources]);

  // Poll while anything is queued or being processed.
  const polling = imports?.some(isInFlight) ?? false;
  React.useEffect(() => {
    if (!polling) return;
    const timer = window.setInterval(() => void loadImports(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [polling, loadImports]);

  const visibleImports =
    imports === null || showAllImports ? imports : imports.slice(0, COLLAPSED_IMPORT_ROWS);

  return (
    <>
      <Card className="overflow-hidden">
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                Imports
                {polling && (
                  <Loader2
                    className="h-4 w-4 animate-spin text-muted-foreground"
                    aria-label="Import in progress"
                  />
                )}
              </CardTitle>
              <CardDescription>
                Recent trade-file imports — uploads and scheduled API pulls.
              </CardDescription>
            </div>
            {canManage && (
              <Button size="sm" className="shrink-0" onClick={() => setWizardOpen(true)}>
                <Upload className="mr-2 h-4 w-4" aria-hidden />
                Import CSV
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {importsError !== null ? (
            <p className="px-6 pb-6 text-sm text-destructive">
              Failed to load imports: {importsError}
            </p>
          ) : imports === null ? (
            <p className="flex items-center gap-2 px-6 pb-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
            </p>
          ) : imports.length === 0 ? (
            <p className="px-6 pb-6 text-sm text-muted-foreground">
              No imports yet{canManage ? " — import a CSV or pull from an API source." : "."}
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Kind</TableHead>
                    <TableHead>Trade date</TableHead>
                    <TableHead>File</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Rows</TableHead>
                    <TableHead className="text-right">Imported</TableHead>
                    <TableHead className="text-right">Skipped</TableHead>
                    <TableHead>Errors</TableHead>
                    <TableHead>Started</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(visibleImports ?? []).map((i) => (
                    <TableRow
                      key={i.id}
                      tabIndex={0}
                      onClick={() => setDetailImport(i)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") setDetailImport(i);
                      }}
                      className="cursor-pointer focus-visible:bg-muted/50 focus-visible:outline-none"
                    >
                      <TableCell>
                        <Badge variant={i.kind === "api_pull" ? "violet" : "info"}>
                          {KIND_LABEL[i.kind] ?? i.kind}
                        </Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{i.trade_date}</TableCell>
                      <TableCell className="max-w-[220px]">
                        <span className="block truncate" title={i.file_name ?? undefined}>
                          {i.file_name ?? "—"}
                        </span>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={i.status} />
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{i.row_count}</TableCell>
                      <TableCell className="text-right tabular-nums">{i.imported_count}</TableCell>
                      <TableCell className="text-right tabular-nums">{i.skipped_count}</TableCell>
                      <TableCell>
                        {i.errors.length > 0 ? (
                          <span
                            className="text-sm text-destructive"
                            title={i.errors
                              .map((e) => (typeof e === "string" ? e : JSON.stringify(e)))
                              .join("\n")}
                          >
                            {i.errors.length} error{i.errors.length === 1 ? "" : "s"}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatDateTime(i.created_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {imports.length > COLLAPSED_IMPORT_ROWS && (
                <div className="border-t px-4 py-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowAllImports((v) => !v)}
                  >
                    {showAllImports
                      ? "Show fewer"
                      : `Show all ${imports.length} imports`}
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <SourcesSection
        sources={sources}
        error={sourcesError}
        canManage={canManage}
        onChanged={() => void loadSources()}
        onImportStarted={() => void loadImports()}
      />

      {wizardOpen && (
        <ImportWizard
          sources={sources ?? []}
          onClose={() => setWizardOpen(false)}
          onDone={() => void loadImports()}
        />
      )}

      {detailImport && (
        <ImportDetail
          imp={detailImport}
          canManage={canManage}
          onClose={() => setDetailImport(null)}
          onDeleted={() => {
            setDetailImport(null);
            void loadImports();
            router.refresh();
          }}
        />
      )}
    </>
  );
}
