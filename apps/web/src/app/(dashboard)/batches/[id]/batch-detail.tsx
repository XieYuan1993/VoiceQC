"use client";

import {
  ArrowLeft,
  FileArchive,
  FileAudio,
  Loader2,
  RefreshCw,
  RotateCcw,
  UploadCloud,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { DeleteBatchButton } from "@/components/delete-batch-button";
import { StageChips, StatusBadge } from "@/components/status-badge";
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
import { apiCall, apiJson, getApiErrorMessage, uploadDirectToStorage } from "@/lib/api";
import { formatBytes, formatDateTime, formatDuration } from "@/lib/format";
import type { Batch, RecordingList, UploadFileResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACCEPTED_EXTS: readonly string[] = [".wav", ".mp3", ".m4a", ".flac", ".ogg", ".zip"];
const UPLOAD_CONCURRENCY = 3;
const POLL_MS = 5000;
const REC_PAGE_SIZE = 50;
const ASR_PROVIDER_OPTIONS = [
  { value: "tencent", label: "Tencent ASR", model: "16k_zh_en" },
  { value: "qwen", label: "Qwen ASR", model: "qwen3-asr-flash" },
  { value: "google", label: "Google STT", model: "chirp_2" },
  { value: "gemini", label: "Gemini audio", model: "gemini-3.5-flash" },
] as const;

type UploadState = "queued" | "uploading" | "done" | "duplicate" | "error";

interface UploadItem {
  id: number;
  name: string;
  size: number;
  state: UploadState;
  progress: number; // 0..1
  kind?: string; // "audio" | "zip", from the server
  message?: string;
}

function UploadStateBadge({ state }: { state: UploadState }) {
  switch (state) {
    case "queued":
      return <Badge variant="neutral">queued</Badge>;
    case "uploading":
      return <Badge variant="info">uploading</Badge>;
    case "done":
      return <Badge variant="success">uploaded</Badge>;
    case "duplicate":
      return <Badge variant="warning">duplicate</Badge>;
    case "error":
      return <Badge variant="destructive">error</Badge>;
  }
}

export function BatchDetail({ batchId, canManage }: { batchId: string; canManage: boolean }) {
  const [batch, setBatch] = React.useState<Batch | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [recordings, setRecordings] = React.useState<RecordingList | null>(null);
  const [recError, setRecError] = React.useState<string | null>(null);
  const [recPage, setRecPage] = React.useState(1);
  const [uploads, setUploads] = React.useState<UploadItem[]>([]);
  const [dragOver, setDragOver] = React.useState(false);
  const [finalizing, setFinalizing] = React.useState(false);
  const [retrying, setRetrying] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [rerunOpen, setRerunOpen] = React.useState(false);
  const [rerunProvider, setRerunProvider] = React.useState("tencent");
  const [rerunModel, setRerunModel] = React.useState("16k_zh_en");
  const [rerunningStt, setRerunningStt] = React.useState(false);

  const batchRef = React.useRef<Batch | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  // Upload queue: ids in queueRef, File objects in pendingFilesRef, at most
  // UPLOAD_CONCURRENCY in flight (tracked by activeRef).
  const pendingFilesRef = React.useRef<Map<number, File>>(new Map());
  const queueRef = React.useRef<number[]>([]);
  const activeRef = React.useRef(0);
  const nextUploadIdRef = React.useRef(1);

  const loadBatch = React.useCallback(async () => {
    try {
      const b = await apiCall("/api/batches/{batch_id}", "get", {
        params: { path: { batch_id: batchId } },
      });
      batchRef.current = b;
      setBatch(b);
      setLoadError(null);
    } catch (e) {
      // Keep showing stale data on transient poll failures; only hard-fail
      // when the first load never succeeded.
      if (batchRef.current === null) setLoadError(getApiErrorMessage(e));
    }
  }, [batchId]);

  const loadRecordings = React.useCallback(
    async (page: number) => {
      try {
        const r = await apiCall("/api/recordings", "get", {
          params: { query: { batch_id: batchId, page, page_size: REC_PAGE_SIZE } },
        });
        setRecordings(r);
        setRecError(null);
      } catch (e) {
        setRecError(getApiErrorMessage(e));
      }
    },
    [batchId],
  );

  const refresh = React.useCallback(() => {
    void loadBatch();
    void loadRecordings(recPage);
  }, [loadBatch, loadRecordings, recPage]);

  React.useEffect(() => {
    void loadBatch();
  }, [loadBatch]);

  React.useEffect(() => {
    void loadRecordings(recPage);
  }, [loadRecordings, recPage]);

  // Poll batch + recordings while the pipeline runs.
  const processing = batch?.status === "processing";
  React.useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(timer);
  }, [processing, refresh]);

  function updateUpload(id: number, patch: Partial<UploadItem>) {
    setUploads((prev) => prev.map((u) => (u.id === id ? { ...u, ...patch } : u)));
  }

  function pump() {
    while (activeRef.current < UPLOAD_CONCURRENCY && queueRef.current.length > 0) {
      const id = queueRef.current.shift();
      if (id === undefined) break;
      const file = pendingFilesRef.current.get(id);
      if (!file) continue;
      pendingFilesRef.current.delete(id);
      activeRef.current += 1;
      updateUpload(id, { state: "uploading", progress: 0 });
      uploadDirectToStorage<UploadFileResult>(`/api/batches/${batchId}`, file, {
        onProgress: (fraction) => updateUpload(id, { progress: fraction }),
      })
        .then((res) => {
          updateUpload(id, {
            state: res.duplicate ? "duplicate" : "done",
            progress: 1,
            kind: res.kind,
          });
        })
        .catch((e: unknown) => {
          updateUpload(id, { state: "error", message: getApiErrorMessage(e) });
        })
        .finally(() => {
          activeRef.current -= 1;
          refresh();
          pump();
        });
    }
  }

  function addFiles(files: File[]) {
    const items: UploadItem[] = [];
    for (const file of files) {
      const dot = file.name.lastIndexOf(".");
      const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
      const id = nextUploadIdRef.current++;
      if (!ACCEPTED_EXTS.includes(ext)) {
        items.push({
          id,
          name: file.name,
          size: file.size,
          state: "error",
          progress: 0,
          message: `Unsupported type — allowed: ${ACCEPTED_EXTS.join(" ")}`,
        });
        continue;
      }
      pendingFilesRef.current.set(id, file);
      queueRef.current.push(id);
      items.push({ id, name: file.name, size: file.size, state: "queued", progress: 0 });
    }
    if (items.length > 0) setUploads((prev) => [...prev, ...items]);
    pump();
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length > 0) addFiles(Array.from(e.dataTransfer.files));
  }

  async function onFinalize() {
    setActionError(null);
    setNotice(null);
    setFinalizing(true);
    try {
      await apiCall("/api/batches/{batch_id}/finalize", "post", {
        params: { path: { batch_id: batchId } },
      });
      refresh();
    } catch (e) {
      setActionError(getApiErrorMessage(e));
    } finally {
      setFinalizing(false);
    }
  }

  async function onRetryFailed() {
    setActionError(null);
    setNotice(null);
    setRetrying(true);
    try {
      const res = await apiCall("/api/batches/{batch_id}/retry-failed", "post", {
        params: { path: { batch_id: batchId } },
      });
      setNotice(`Retrying ${res.retried} failed recording${res.retried === 1 ? "" : "s"}.`);
      refresh();
    } catch (e) {
      setActionError(getApiErrorMessage(e));
    } finally {
      setRetrying(false);
    }
  }

  function onRerunProviderChange(provider: string) {
    setRerunProvider(provider);
    setRerunModel(ASR_PROVIDER_OPTIONS.find((opt) => opt.value === provider)?.model ?? "");
  }

  async function onRerunStt() {
    setActionError(null);
    setNotice(null);
    setRerunningStt(true);
    try {
      const model = rerunModel.trim();
      const res = await apiJson<{ queued: number }>(`/api/batches/${batchId}/rerun-stt`, "post", {
        body: {
          asr_provider: rerunProvider,
          asr_model: model.length > 0 ? model : null,
        },
      });
      setNotice(`Queued ${res.queued} recording${res.queued === 1 ? "" : "s"} for STT rerun.`);
      setRerunOpen(false);
      refresh();
    } catch (e) {
      setActionError(getApiErrorMessage(e));
    } finally {
      setRerunningStt(false);
    }
  }

  if (loadError !== null && batch === null) {
    return (
      <div className="space-y-4">
        <Link
          href="/batches"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden /> Back to batches
        </Link>
        <Card>
          <CardContent className="p-6 text-sm text-destructive">
            Failed to load batch: {loadError}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (batch === null) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading batch…
      </div>
    );
  }

  const counts = batch.counts ?? null;
  const countsSum = counts
    ? counts.uploaded +
      counts.converting +
      counts.transcribing +
      counts.evaluating +
      counts.completed +
      counts.failed
    : 0;
  const serverFileCount = Math.max(batch.total_files, countsSum);
  const uploadsInFlight = uploads.some((u) => u.state === "queued" || u.state === "uploading");
  const hasFiles = serverFileCount > 0 || uploads.some((u) => u.state === "done");
  const canFinalize = hasFiles && !uploadsInFlight;
  const recPageCount = recordings ? Math.max(1, Math.ceil(recordings.total / REC_PAGE_SIZE)) : 1;

  return (
    <div className="space-y-6">
      <Link
        href="/batches"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden /> Back to batches
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold">{batch.name ?? batch.trade_date}</h1>
            <StatusBadge status={batch.status} />
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Batch date {batch.trade_date} · {serverFileCount} file
            {serverFileCount === 1 ? "" : "s"} · created {formatDateTime(batch.created_at)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {canManage && counts !== null && counts.failed > 0 && (
            <Button variant="outline" onClick={onRetryFailed} disabled={retrying}>
              {retrying ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
              )}
              Retry failed ({counts.failed})
            </Button>
          )}
          {canManage && batch.status !== "open" && serverFileCount > 0 && (
            <Button variant="outline" onClick={() => setRerunOpen(true)} disabled={rerunningStt}>
              {rerunningStt ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <RotateCcw className="mr-2 h-4 w-4" aria-hidden />
              )}
              Rerun STT
            </Button>
          )}
          {canManage && batch.status === "open" && (
            <Button onClick={onFinalize} disabled={!canFinalize || finalizing}>
              {finalizing && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              Finalize batch
            </Button>
          )}
          {canManage && (
            <DeleteBatchButton
              batchId={batch.id}
              batchName={batch.name ?? String(batch.trade_date)}
              fileCount={serverFileCount}
              variant="button"
              redirectTo="/batches"
            />
          )}
        </div>
      </div>

      {actionError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive">
          {actionError}
        </div>
      )}
      {notice && (
        <div className="rounded-md border border-emerald-300/60 bg-emerald-50 px-4 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
          {notice}
        </div>
      )}

      {counts !== null && countsSum > 0 && batch.status !== "open" && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              Pipeline progress
              {processing && (
                <Loader2
                  className="h-4 w-4 animate-spin text-muted-foreground"
                  aria-label="Processing"
                />
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <StageChips counts={counts} />
          </CardContent>
        </Card>
      )}

      {canManage && batch.status === "open" && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Upload recordings</CardTitle>
            <CardDescription>
              Audio files or a ZIP of recordings. Finalize when everything is uploaded to start
              transcription.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div
              role="button"
              tabIndex={0}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
                dragOver
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50 hover:bg-muted/40",
              )}
            >
              <UploadCloud className="h-8 w-8 text-muted-foreground" aria-hidden />
              <p className="text-sm font-medium">
                Drag &amp; drop recordings here, or click to browse
              </p>
              <p className="text-xs text-muted-foreground">
                {ACCEPTED_EXTS.join(" ")} · up to {UPLOAD_CONCURRENCY} uploads at a time
              </p>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPTED_EXTS.join(",")}
              className="hidden"
              onChange={(e) => {
                if (e.target.files) addFiles(Array.from(e.target.files));
                e.target.value = "";
              }}
            />

            {uploads.length > 0 && (
              <ul className="divide-y rounded-md border">
                {uploads.map((u) => (
                  <li key={u.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                    {u.kind === "zip" || u.name.toLowerCase().endsWith(".zip") ? (
                      <FileArchive className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                    ) : (
                      <FileAudio className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="truncate font-medium">{u.name}</span>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {formatBytes(u.size)}
                        </span>
                      </div>
                      {u.state === "uploading" && (
                        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full rounded-full bg-primary transition-all"
                            style={{ width: `${Math.round(u.progress * 100)}%` }}
                          />
                        </div>
                      )}
                      {u.state === "error" && u.message && (
                        <p className="mt-0.5 text-xs text-destructive">{u.message}</p>
                      )}
                      {u.state === "duplicate" && (
                        <p className="mt-0.5 text-xs text-amber-700 dark:text-amber-400">
                          Already in this batch — skipped.
                        </p>
                      )}
                      {u.state === "done" && u.kind === "zip" && (
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          ZIP stored — expands into recordings on finalize.
                        </p>
                      )}
                    </div>
                    <UploadStateBadge state={u.state} />
                  </li>
                ))}
              </ul>
            )}

            {batch.status === "open" && !hasFiles && (
              <p className="text-xs text-muted-foreground">
                Upload at least one file to enable Finalize.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <Card className="overflow-hidden">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            Recordings
            {recordings !== null && (
              <span className="text-sm font-normal text-muted-foreground">
                ({recordings.total})
              </span>
            )}
            {processing && (
              <Loader2
                className="h-4 w-4 animate-spin text-muted-foreground"
                aria-label="Refreshing"
              />
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {recError !== null ? (
            <p className="px-6 pb-6 text-sm text-destructive">
              Failed to load recordings: {recError}
            </p>
          ) : recordings === null ? (
            <p className="flex items-center gap-2 px-6 pb-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
            </p>
          ) : recordings.items.length === 0 ? (
            <p className="px-6 pb-6 text-sm text-muted-foreground">
              {batch.status === "open"
                ? "Uploaded audio files appear here. ZIP contents appear after finalize."
                : "No recordings in this batch."}
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Filename</TableHead>
                    <TableHead>Agent</TableHead>
                    <TableHead>Call time</TableHead>
                    <TableHead className="text-right">Duration</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recordings.items.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className="max-w-[320px]">
                        <Link
                          href={`/recordings/${r.id}`}
                          className="block truncate font-medium text-primary hover:underline"
                          title={r.original_filename}
                        >
                          {r.original_filename}
                        </Link>
                      </TableCell>
                      <TableCell>{r.broker_ext ?? "—"}</TableCell>
                      <TableCell className="whitespace-nowrap">
                        {formatDateTime(r.call_started_at)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatDuration(r.duration_seconds)}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={r.status} />
                      </TableCell>
                      <TableCell className="text-right">
                        <Link
                          href={`/recordings/${r.id}`}
                          className="text-sm text-primary hover:underline"
                        >
                          View
                        </Link>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {recordings.total > REC_PAGE_SIZE && (
                <div className="flex items-center justify-between border-t px-4 py-3 text-sm">
                  <span className="text-muted-foreground">
                    Page {recordings.page} of {recPageCount}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={recPage <= 1}
                      onClick={() => setRecPage((p) => p - 1)}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={recPage >= recPageCount}
                      onClick={() => setRecPage((p) => p + 1)}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={rerunOpen} onOpenChange={setRerunOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rerun STT</DialogTitle>
            <DialogDescription>
              Re-transcribe recordings in this batch and replace existing transcripts.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="asr-provider">ASR provider</Label>
              <Select
                id="asr-provider"
                value={rerunProvider}
                onChange={(e) => onRerunProviderChange(e.target.value)}
              >
                {ASR_PROVIDER_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="asr-model">Model</Label>
              <Input
                id="asr-model"
                value={rerunModel}
                onChange={(e) => setRerunModel(e.target.value)}
                placeholder="Provider default"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRerunOpen(false)} disabled={rerunningStt}>
              Cancel
            </Button>
            <Button onClick={onRerunStt} disabled={rerunningStt}>
              {rerunningStt && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              Rerun
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
