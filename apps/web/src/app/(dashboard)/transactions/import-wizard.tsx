"use client";

import { ArrowLeft, Download, FileSpreadsheet, Loader2 } from "lucide-react";
import * as React from "react";

import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { apiCall, getApiErrorMessage, uploadMultipart } from "@/lib/api";
import type { TxnDryRun, TxnImport, TxnSource } from "@/lib/types";

const ACCEPTED_EXTS = ".csv,.xlsx,.xls";
const POLL_MS = 5000;

// Canonical-row keys from the dry-run preview, in display order. Anything
// unexpected the backend adds still shows, appended after these.
const PREVIEW_COLUMNS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "trade_date", label: "Trade date" },
  { key: "ext_txn_id", label: "Ext ref" },
  { key: "broker_code", label: "Broker" },
  { key: "client_account", label: "Account" },
  { key: "client_name", label: "Client" },
  { key: "stock_code", label: "Stock" },
  { key: "side", label: "Side" },
  { key: "quantity", label: "Qty" },
  { key: "price", label: "Price" },
  { key: "channel", label: "Channel" },
  { key: "skip_reason", label: "Skip" },
];

// Example value per canonical field for the downloadable template. side/channel
// are overridden from the chosen template's own accepted values.
const TEMPLATE_EXAMPLES: Record<string, [string, string]> = {
  trade_date: ["2025-11-18", "2025-11-18"],
  ordered_at: ["2025-11-18 09:40:32 HKT", "2025-11-18 10:05:11 HKT"],
  executed_at: ["2025-11-18 09:41:00 HKT", "2025-11-18 10:05:40 HKT"],
  ext_txn_id: ["1175249150931398656", "1175249150931398999"],
  broker_code: ["QUAMIBFH02A", "QUAMIBH0048"],
  client_account: ["0188-100234", "0188-100567"],
  client_name: ["高荣利", "謝輝光"],
  stock_code: ["1208", "135"],
  stock_name: ["五礦資源", "昆崙能源"],
  side: ["買入", "賣出"],
  quantity: ["48,000", "6,000"],
  price: ["6.6500", "7.3700"],
  amount: ["319200.00", "44220.00"],
  channel: ["WTT", "WTT"],
};

type Step = "select" | "preview" | "importing" | "done";

function cellText(v: unknown): string {
  if (v == null || v === "") return "—";
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

function csvCell(v: string): string {
  return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

/** Build + download a sample CSV whose columns match the chosen mapping template. */
function downloadTemplate(source: TxnSource | undefined): void {
  const cfg = (source?.config ?? {}) as Record<string, unknown>;
  const mapping = (cfg.column_mapping ?? {}) as Record<string, string>;
  const cols = Object.entries(mapping); // [canonicalKey, sourceColumnName]
  if (cols.length === 0) return;

  const sideValues = (cfg.side_values ?? {}) as Record<string, string[]>;
  const channelValues = (cfg.channel_values ?? {}) as Record<string, string[]>;
  const examples: Record<string, [string, string]> = { ...TEMPLATE_EXAMPLES };
  const buy = sideValues.buy?.[0];
  const sell = sideValues.sell?.[0];
  if (buy && sell) examples.side = [buy, sell];
  const chan = Object.values(channelValues)[0]?.[0];
  if (chan) examples.channel = [chan, chan];

  const header = cols.map(([, col]) => csvCell(col)).join(",");
  const rows = [0, 1].map((i) =>
    cols.map(([canon]) => csvCell(examples[canon]?.[i] ?? "")).join(","),
  );
  // Prepend a UTF-8 BOM so Excel renders the Chinese column values correctly.
  const blob = new Blob(["﻿" + [header, ...rows].join("\r\n")], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${(source?.name ?? "trade").replace(/[^\w.-]+/g, "_")}_template.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function ImportWizard({
  sources,
  onClose,
  onDone,
}: {
  sources: TxnSource[];
  onClose: () => void;
  /** Called when an import was started (and again as it settles). */
  onDone: () => void;
}) {
  const csvSources = sources.filter((s) => s.kind === "csv");

  const [step, setStep] = React.useState<Step>("select");
  const [file, setFile] = React.useState<File | null>(null);
  const [sourceId, setSourceId] = React.useState(csvSources[0]?.id ?? "");
  const [tradeDate, setTradeDate] = React.useState("");
  const [dryRun, setDryRun] = React.useState<TxnDryRun | null>(null);
  const [imp, setImp] = React.useState<TxnImport | null>(null);
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const startedRef = React.useRef(false);
  const selectedSource = csvSources.find((s) => s.id === sourceId);

  // Per-row dates the file carries (empty => the file has no date column).
  const fileDates = dryRun?.trade_dates ?? [];
  const needsManualDate = dryRun !== null && fileDates.length === 0;

  async function onPreview() {
    if (!file || !sourceId) {
      setError("Pick a file and a mapping template.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const res = await uploadMultipart<TxnDryRun>("/api/txn-imports/csv/dry-run", file, {
        fields: { source_config_id: sourceId },
      });
      setDryRun(res);
      setStep("preview");
    } catch (e) {
      setError(getApiErrorMessage(e));
    } finally {
      setPending(false);
    }
  }

  async function onImport() {
    if (!file || !sourceId) return;
    if (needsManualDate && !tradeDate) return;
    setPending(true);
    setError(null);
    try {
      // Only send a trade date for files that don't carry one; otherwise each row
      // keeps its own date from the sheet.
      const fields: Record<string, string> = { source_config_id: sourceId };
      if (needsManualDate && tradeDate) fields.trade_date = tradeDate;
      const res = await uploadMultipart<TxnImport>("/api/txn-imports/csv", file, { fields });
      setImp(res);
      startedRef.current = true;
      setStep(res.status === "completed" || res.status === "failed" ? "done" : "importing");
      onDone(); // imports list shows the new row right away
    } catch (e) {
      setError(getApiErrorMessage(e));
    } finally {
      setPending(false);
    }
  }

  // Poll until the queued import settles.
  const importId = imp?.id;
  React.useEffect(() => {
    if (step !== "importing" || !importId) return;
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const list = await apiCall("/api/txn-imports", "get");
          const found = list.find((i) => i.id === importId);
          if (found) {
            setImp(found);
            if (found.status === "completed" || found.status === "failed") {
              setStep("done");
              onDone(); // refresh imports + transactions now that rows landed
            }
          }
        } catch {
          // transient poll failure — keep trying
        }
      })();
    }, POLL_MS);
    return () => window.clearInterval(timer);
    // onDone is stable enough for our purposes; re-subscribing on it is fine.
  }, [step, importId, onDone]);

  function close() {
    onClose();
  }

  // Extra columns the backend may add beyond the known canonical set.
  const previewExtraKeys =
    dryRun === null
      ? []
      : Array.from(
          new Set(dryRun.preview.flatMap((row) => Object.keys(row))),
        ).filter((k) => !PREVIEW_COLUMNS.some((c) => c.key === k) && k !== "ordered_at" && k !== "executed_at");

  return (
    <Dialog open onOpenChange={(o) => !o && close()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Import trade file</DialogTitle>
          <DialogDescription>
            {step === "select" && "Pick the trade file and the mapping template — the trade date is read from the file."}
            {step === "preview" && "Dry run only — nothing is imported until you confirm."}
            {step === "importing" && "Importing — this dialog tracks the queued job."}
            {step === "done" && "Import finished."}
          </DialogDescription>
        </DialogHeader>

        {step === "select" && (
          <div className="space-y-4">
            {csvSources.length === 0 ? (
              <p className="rounded-md border border-amber-300/60 bg-amber-50 px-4 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
                No CSV mapping template configured yet — create a source of kind
                &quot;csv&quot; in the Sources section first.
              </p>
            ) : (
              <>
                <div className="space-y-2">
                  <Label htmlFor="import-file">Trade file (.csv / .xlsx)</Label>
                  <Input
                    id="import-file"
                    type="file"
                    accept={ACCEPTED_EXTS}
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    className="cursor-pointer pt-2"
                  />
                  {file && (
                    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <FileSpreadsheet className="h-3.5 w-3.5" aria-hidden />
                      {file.name}
                    </p>
                  )}
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="import-source">Mapping template</Label>
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-auto px-1 py-0.5 text-xs"
                      onClick={() => downloadTemplate(selectedSource)}
                      disabled={!selectedSource}
                    >
                      <Download className="mr-1 h-3.5 w-3.5" aria-hidden />
                      Download template
                    </Button>
                  </div>
                  <Select
                    id="import-source"
                    value={sourceId}
                    onChange={(e) => setSourceId(e.target.value)}
                  >
                    {csvSources.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    The trade date comes from the file. Download the template to see the expected columns.
                  </p>
                </div>
              </>
            )}
            {error && <p className="text-sm text-destructive">{error}</p>}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={close}>
                Cancel
              </Button>
              <Button onClick={onPreview} disabled={pending || !file || !sourceId}>
                {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
                Preview
              </Button>
            </DialogFooter>
          </div>
        )}

        {step === "preview" && dryRun !== null && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="neutral">
                <span className="font-semibold tabular-nums">{dryRun.rows_total}</span>
                &nbsp;rows
              </Badge>
              <Badge variant="success">
                <span className="font-semibold tabular-nums">{dryRun.importable}</span>
                &nbsp;importable
              </Badge>
              {dryRun.skipped_duplicate > 0 && (
                <Badge variant="neutral">
                  <span className="font-semibold tabular-nums">{dryRun.skipped_duplicate}</span>
                  &nbsp;fill rows merged
                </Badge>
              )}
              {dryRun.skipped_status > 0 && (
                <Badge variant="warning">
                  <span className="font-semibold tabular-nums">{dryRun.skipped_status}</span>
                  &nbsp;skipped (status)
                </Badge>
              )}
              {dryRun.skipped_side > 0 && (
                <Badge variant="warning">
                  <span className="font-semibold tabular-nums">{dryRun.skipped_side}</span>
                  &nbsp;skipped (side)
                </Badge>
              )}
            </div>

            {fileDates.length > 0 ? (
              <p className="rounded-md border border-emerald-300/60 bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
                Trade date{fileDates.length > 1 ? "s" : ""} read from the file:{" "}
                <span className="font-semibold tabular-nums">{fileDates.join(", ")}</span>
                {fileDates.length > 1 && " — each row keeps its own date."}
              </p>
            ) : (
              <div className="space-y-1.5">
                <Label htmlFor="import-trade-date">Trade date</Label>
                <Input
                  id="import-trade-date"
                  type="date"
                  required
                  value={tradeDate}
                  onChange={(e) => setTradeDate(e.target.value)}
                  className="max-w-[200px]"
                />
                <p className="text-xs text-muted-foreground">
                  This file has no date column — set the trade date for these rows.
                </p>
              </div>
            )}

            {dryRun.preview.length === 0 ? (
              <p className="text-sm text-muted-foreground">No parseable rows in this file.</p>
            ) : (
              <div className="max-h-72 overflow-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      {PREVIEW_COLUMNS.map((c) => (
                        <TableHead key={c.key}>{c.label}</TableHead>
                      ))}
                      {previewExtraKeys.map((k) => (
                        <TableHead key={k}>{k}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {dryRun.preview.map((row, i) => {
                      const skipped = row.skip_reason != null;
                      return (
                        <TableRow key={i} className={skipped ? "opacity-60" : undefined}>
                          {PREVIEW_COLUMNS.map((c) => (
                            <TableCell
                              key={c.key}
                              className="whitespace-nowrap py-2 text-xs tabular-nums"
                            >
                              {c.key === "skip_reason" && skipped ? (
                                <Badge variant="warning">{cellText(row[c.key])}</Badge>
                              ) : (
                                cellText(row[c.key])
                              )}
                            </TableCell>
                          ))}
                          {previewExtraKeys.map((k) => (
                            <TableCell key={k} className="whitespace-nowrap py-2 text-xs">
                              {cellText(row[k])}
                            </TableCell>
                          ))}
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              Showing the first {dryRun.preview.length} parsed rows.
            </p>

            {error && <p className="text-sm text-destructive">{error}</p>}
            <DialogFooter className="sm:justify-between">
              <Button type="button" variant="ghost" onClick={() => setStep("select")}>
                <ArrowLeft className="mr-1 h-4 w-4" aria-hidden />
                Back
              </Button>
              <div className="flex gap-2">
                <Button type="button" variant="outline" onClick={close}>
                  Cancel
                </Button>
                <Button
                  onClick={onImport}
                  disabled={pending || dryRun.importable === 0 || (needsManualDate && !tradeDate)}
                >
                  {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
                  Import {dryRun.importable} row{dryRun.importable === 1 ? "" : "s"}
                </Button>
              </div>
            </DialogFooter>
          </div>
        )}

        {(step === "importing" || step === "done") && imp !== null && (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              {step === "importing" ? (
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
              ) : null}
              <StatusBadge status={imp.status} />
              <span className="text-sm text-muted-foreground">
                {imp.file_name ?? "trade file"} · trade date {imp.trade_date}
              </span>
            </div>
            <dl className="grid grid-cols-3 gap-4 rounded-md border p-4 text-sm">
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
            {imp.errors.length > 0 && (
              <div className="max-h-32 overflow-y-auto rounded-md border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
                {imp.errors.map((e, i) => (
                  <p key={i}>{typeof e === "string" ? e : JSON.stringify(e)}</p>
                ))}
              </div>
            )}
            <DialogFooter>
              <Button onClick={close} variant={step === "done" ? "default" : "outline"}>
                {step === "done" ? "Done" : "Close (keeps running)"}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
