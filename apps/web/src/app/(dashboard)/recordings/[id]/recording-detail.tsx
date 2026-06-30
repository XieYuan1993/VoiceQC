"use client";

import { ArrowLeft, AudioLines, ChevronDown, Clock, FileText, Loader2, Sparkles } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { API_URL, ApiError, apiCall, getApiErrorMessage } from "@/lib/api";
import { formatBytes, formatDateTime, formatDuration, formatMs } from "@/lib/format";
import type { RecordingDetail, Transcript, TranscriptSegment } from "@/lib/types";
import { cn } from "@/lib/utils";

import { EvaluationPanel } from "./evaluation-panel";

const POLL_MS = 5000;
// Statuses the pipeline moves through on its own — poll while in one.
const IN_FLIGHT = ["uploaded", "converting", "transcribing", "evaluating"];
// Reprocess 409s while one of these is running.
const BUSY = ["converting", "transcribing", "evaluating"];

// Where each call-detail field comes from — surfaced as a small icon + tooltip.
const SOURCE_META = {
  filename: { label: "Parsed from the file name", Icon: FileText },
  call: { label: "Heard in the call (extracted by AI)", Icon: Sparkles },
  audio: { label: "Read from the audio file", Icon: AudioLines },
  system: { label: "Recorded by the system", Icon: Clock },
} as const;

type MetaSource = keyof typeof SOURCE_META;

function MetaItem({
  label,
  source,
  children,
}: {
  label: string;
  source?: MetaSource;
  children: React.ReactNode;
}) {
  const src = source ? SOURCE_META[source] : null;
  const SrcIcon = src?.Icon;
  return (
    <div>
      <dt className="flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
        {src && SrcIcon && (
          <span title={src.label} className="inline-flex cursor-help">
            <SrcIcon className="h-3 w-3 text-muted-foreground/60" aria-label={src.label} />
          </span>
        )}
      </dt>
      <dd className="mt-0.5 text-sm">{children}</dd>
    </div>
  );
}

function ReprocessMenu({
  disabled,
  pending,
  onSelect,
}: {
  disabled: boolean;
  pending: boolean;
  onSelect: (fromStage: "convert" | "stt") => void;
}) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <Button
        variant="outline"
        disabled={disabled || pending}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
        Reprocess
        <ChevronDown className="ml-2 h-4 w-4" aria-hidden />
      </Button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 w-48 rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
        >
          <button
            type="button"
            role="menuitem"
            className="block w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground"
            onClick={() => {
              setOpen(false);
              onSelect("convert");
            }}
          >
            From convert
            <span className="block text-xs text-muted-foreground">
              Re-run audio normalization + STT
            </span>
          </button>
          <button
            type="button"
            role="menuitem"
            className="block w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground"
            onClick={() => {
              setOpen(false);
              onSelect("stt");
            }}
          >
            From STT
            <span className="block text-xs text-muted-foreground">
              Keep converted audio, redo transcription
            </span>
          </button>
        </div>
      )}
    </div>
  );
}

/** Generic display label for a transcript channel role. */
function roleLabel(role: string): string {
  if (role === "broker") return "Agent";
  if (role === "customer") return "Customer";
  return "Speaker";
}

function SegmentBubble({
  segment,
  onSeek,
  flash,
  innerRef,
}: {
  segment: TranscriptSegment;
  onSeek: (ms: number) => void;
  flash?: boolean;
  innerRef?: (el: HTMLButtonElement | null) => void;
}) {
  const role = segment.channel_role;
  const isBroker = role === "broker";
  const isCustomer = role === "customer";
  const mixed = !isBroker && !isCustomer;

  return (
    <div className={cn("flex", isBroker && "justify-start", isCustomer && "justify-end")}>
      <button
        type="button"
        ref={innerRef}
        onClick={() => onSeek(segment.start_ms)}
        title="Play from here"
        className={cn(
          "rounded-lg border px-3 py-2 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          mixed
            ? "w-full bg-muted/60 hover:bg-muted"
            : isBroker
              ? "max-w-[80%] border-blue-200 bg-blue-50 hover:bg-blue-100 dark:border-blue-900 dark:bg-blue-950/40 dark:hover:bg-blue-950/70"
              : "max-w-[80%] border-emerald-200 bg-emerald-50 hover:bg-emerald-100 dark:border-emerald-900 dark:bg-emerald-950/40 dark:hover:bg-emerald-950/70",
          flash && "ring-2 ring-primary ring-offset-2 ring-offset-background",
        )}
      >
        <span className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-medium">{roleLabel(role)}</span>
          <span className="tabular-nums">{formatMs(segment.start_ms)}</span>
          {segment.language && (
            <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
              {segment.language}
            </Badge>
          )}
        </span>
        <span className="block whitespace-pre-wrap">{segment.text}</span>
      </button>
    </div>
  );
}

export function RecordingDetailView({
  recordingId,
  canManage,
  canReview,
}: {
  recordingId: string;
  canManage: boolean;
  canReview: boolean;
}) {
  const [rec, setRec] = React.useState<RecordingDetail | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [transcript, setTranscript] = React.useState<Transcript | null>(null);
  const [transcriptMissing, setTranscriptMissing] = React.useState(false);
  const [transcriptError, setTranscriptError] = React.useState<string | null>(null);
  const [showRaw, setShowRaw] = React.useState(false);
  const [reprocessing, setReprocessing] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [flashIdx, setFlashIdx] = React.useState<number | null>(null);

  const recRef = React.useRef<RecordingDetail | null>(null);
  const audioRef = React.useRef<HTMLAudioElement>(null);
  const segmentRefs = React.useRef(new Map<number, HTMLButtonElement>());
  const flashTimer = React.useRef<number | null>(null);

  const loadRecording = React.useCallback(async () => {
    try {
      const r = await apiCall("/api/recordings/{recording_id}", "get", {
        params: { path: { recording_id: recordingId } },
      });
      recRef.current = r;
      setRec(r);
      setLoadError(null);
    } catch (e) {
      if (recRef.current === null) setLoadError(getApiErrorMessage(e));
    }
  }, [recordingId]);

  const loadTranscript = React.useCallback(async () => {
    try {
      const t = await apiCall("/api/recordings/{recording_id}/transcript", "get", {
        params: { path: { recording_id: recordingId } },
      });
      setTranscript(t);
      setTranscriptMissing(false);
      setTranscriptError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setTranscript(null);
        setTranscriptMissing(true);
        setTranscriptError(null);
      } else {
        setTranscriptError(getApiErrorMessage(e));
      }
    }
  }, [recordingId]);

  React.useEffect(() => {
    void loadRecording();
    void loadTranscript();
  }, [loadRecording, loadTranscript]);

  // Light polling while the pipeline works on this recording.
  const status = rec?.status;
  const inFlight = status !== undefined && IN_FLIGHT.includes(status);
  React.useEffect(() => {
    if (!inFlight) return;
    const timer = window.setInterval(() => void loadRecording(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [inFlight, loadRecording]);

  // When processing finishes, pick up the fresh transcript.
  const prevStatusRef = React.useRef<string | undefined>(undefined);
  React.useEffect(() => {
    if (
      prevStatusRef.current !== undefined &&
      prevStatusRef.current !== status &&
      status === "completed"
    ) {
      void loadTranscript();
    }
    prevStatusRef.current = status;
  }, [status, loadTranscript]);

  function seekTo(ms: number) {
    const el = audioRef.current;
    if (!el) return;
    const t = ms / 1000;
    if (el.readyState >= 1) {
      el.currentTime = t;
      void el.play().catch(() => {});
    } else {
      el.addEventListener(
        "loadedmetadata",
        () => {
          el.currentTime = t;
          void el.play().catch(() => {});
        },
        { once: true },
      );
      el.load();
    }
  }

  // Evidence click: seek the player AND scroll/flash the transcript segment
  // the timestamp falls into (or the closest one before it).
  function jumpToEvidence(ms: number) {
    seekTo(ms);
    const segments = transcript?.segments;
    if (!segments || segments.length === 0) return;
    let idx = 0;
    for (let i = 0; i < segments.length; i++) {
      const s = segments[i];
      if (ms >= s.start_ms && ms <= s.end_ms) {
        idx = i;
        break;
      }
      if (s.start_ms <= ms) idx = i;
    }
    segmentRefs.current.get(idx)?.scrollIntoView({ behavior: "smooth", block: "center" });
    setFlashIdx(idx);
    if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlashIdx(null), 1600);
  }

  React.useEffect(
    () => () => {
      if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    },
    [],
  );

  async function onReprocess(fromStage: "convert" | "stt") {
    setActionError(null);
    setNotice(null);
    setReprocessing(true);
    try {
      await apiCall("/api/recordings/{recording_id}/reprocess", "post", {
        params: { path: { recording_id: recordingId }, query: { from_stage: fromStage } },
      });
      setNotice(`Reprocess queued (from ${fromStage}).`);
      await loadRecording();
    } catch (e) {
      setActionError(getApiErrorMessage(e));
    } finally {
      setReprocessing(false);
    }
  }

  if (loadError !== null && rec === null) {
    return (
      <div className="space-y-4">
        <Link
          href="/recordings"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden /> Back to recordings
        </Link>
        <Card>
          <CardContent className="p-6 text-sm text-destructive">
            Failed to load recording: {loadError}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (rec === null) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading recording…
      </div>
    );
  }

  const busy = BUSY.includes(rec.status);

  return (
    <div className="space-y-6">
      <Link
        href="/recordings"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden /> Back to recordings
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="truncate text-2xl font-semibold" title={rec.original_filename}>
              {rec.original_filename}
            </h1>
            <StatusBadge status={rec.status} />
            {inFlight && (
              <Loader2
                className="h-4 w-4 animate-spin text-muted-foreground"
                aria-label="Processing"
              />
            )}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {formatDateTime(rec.call_started_at)} · {formatDuration(rec.duration_seconds)} ·{" "}
            <Link href={`/batches/${rec.batch_id}`} className="text-primary hover:underline">
              View batch
            </Link>
          </p>
        </div>
        {canManage && (
          <ReprocessMenu disabled={busy} pending={reprocessing} onSelect={onReprocess} />
        )}
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

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Call details</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
                <MetaItem label="Agent" source="filename">
                  {rec.broker_ext ?? "—"}
                </MetaItem>
                <MetaItem label="Client" source="call">
                  {rec.client_name ?? "—"}
                  {rec.client_account && (
                    <span className="text-muted-foreground"> · {rec.client_account}</span>
                  )}
                </MetaItem>
                <MetaItem label="Caller no." source="filename">
                  {rec.caller_number || "—"}
                </MetaItem>
                <MetaItem label="Direction" source="filename">
                  <span className="capitalize">{rec.direction}</span>
                </MetaItem>
                <MetaItem label="Call time" source="filename">
                  {formatDateTime(rec.call_started_at)}
                </MetaItem>
                <MetaItem label="Duration" source="audio">
                  {formatDuration(rec.duration_seconds)}
                </MetaItem>
                <MetaItem label="Size" source="audio">
                  {formatBytes(rec.size_bytes)}
                </MetaItem>
                <MetaItem label="Channels" source="audio">
                  {rec.channels ?? "—"}
                  {rec.sample_rate != null && (
                    <span className="text-muted-foreground"> · {rec.sample_rate} Hz</span>
                  )}
                </MetaItem>
                <MetaItem label="Uploaded" source="system">
                  {formatDateTime(rec.created_at)}
                </MetaItem>
              </dl>
              <p className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <FileText className="h-3 w-3" aria-hidden /> from file name
                </span>
                <span className="inline-flex items-center gap-1">
                  <Sparkles className="h-3 w-3" aria-hidden /> heard in call (AI)
                </span>
                <span className="inline-flex items-center gap-1">
                  <AudioLines className="h-3 w-3" aria-hidden /> from audio
                </span>
              </p>
              {rec.status === "failed" && (
                <div className="mt-4 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm">
                  <p className="font-medium text-destructive">
                    Failed{rec.failed_stage ? ` at ${rec.failed_stage}` : ""}
                  </p>
                  {rec.error && (
                    <p className="mt-1 break-words text-xs text-destructive/90">{rec.error}</p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Audio</CardTitle>
              <CardDescription>Click a transcript segment to jump the playhead.</CardDescription>
            </CardHeader>
            <CardContent>
              {/* The endpoint 302s to a short-lived signed URL; credentials
                  ride along for the API hop (CORS allows them from :3020). */}
              <audio
                ref={audioRef}
                controls
                crossOrigin="use-credentials"
                preload="metadata"
                src={`${API_URL}/api/recordings/${recordingId}/audio`}
                className="w-full"
              />
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-3">
            <div>
              <CardTitle className="text-base">Transcript</CardTitle>
              {transcript && (
                <CardDescription className="mt-1">
                  {transcript.stt_model}
                  {transcript.language_detected ? ` · ${transcript.language_detected}` : ""}
                  {transcript.billed_seconds != null
                    ? ` · ${formatDuration(transcript.billed_seconds)} billed`
                    : ""}
                </CardDescription>
              )}
            </div>
            {transcript && transcript.full_text && (
              <Button variant="ghost" size="sm" onClick={() => setShowRaw((v) => !v)}>
                {showRaw ? "Hide raw text" : "Show raw text"}
              </Button>
            )}
          </CardHeader>
          <CardContent>
            {transcriptError !== null ? (
              <p className="text-sm text-destructive">
                Failed to load transcript: {transcriptError}
              </p>
            ) : transcriptMissing ? (
              <p className="text-sm text-muted-foreground">
                No transcript yet
                {inFlight ? " — this recording is still being processed." : "."}
              </p>
            ) : transcript === null ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
              </p>
            ) : (
              <div className="space-y-4">
                {showRaw && (
                  <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md border bg-muted/50 p-3 font-mono text-xs">
                    {transcript.full_text}
                  </pre>
                )}
                {transcript.segments.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No timed segments — use the raw text above.
                  </p>
                ) : (
                  <div className="max-h-[36rem] space-y-2 overflow-y-auto pr-1">
                    {transcript.segments.map((s, i) => (
                      <SegmentBubble
                        key={i}
                        segment={s}
                        onSeek={seekTo}
                        flash={flashIdx === i}
                        innerRef={(el) => {
                          if (el) segmentRefs.current.set(i, el);
                          else segmentRefs.current.delete(i);
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <EvaluationPanel
        recordingId={recordingId}
        recordingStatus={rec.status}
        canReview={canReview}
        onJump={jumpToEvidence}
        onRecordingChanged={() => void loadRecording()}
      />
    </div>
  );
}
