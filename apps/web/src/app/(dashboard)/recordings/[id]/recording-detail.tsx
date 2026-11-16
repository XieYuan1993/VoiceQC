"use client";

import {
  ArrowLeft,
  AudioLines,
  ChevronDown,
  Clock,
  Download,
  FileText,
  Loader2,
  Pencil,
  Tag,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { StatusBadge } from "@/components/status-badge";
import { KnowledgeCardDialog } from "@/components/knowledge-card-dialog";
import { knowledgeTriggerRanges } from "@/lib/knowledge-trigger-highlights";
import { TranscriptKnowledgeHints } from "./transcript-knowledge-hints";
import { SupervisorAlert, useSupervisorContact } from "./supervisor-alert";
import { complaintTrigger } from "@/lib/supervisor-notification";
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
import type { KnowledgeCard, RecordingDetail, Transcript, TranscriptSegment } from "@/lib/types";
import { cn } from "@/lib/utils";

import { EvaluationPanel } from "./evaluation-panel";
import { CrsPanel } from "./crs-panel";
import { TranscriptEditor } from "./transcript-editor";

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
  onSelect: (fromStage: "convert" | "stt", provider?: string, model?: string) => void;
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
          <div className="my-1 border-t" />
          {([['manual_split_16k_yue', 'Dyna 粵語'], ['manual_split_16k', 'Dyna 普通話']] as const).map(([model, label]) => <button type="button" role="menuitem" key={model} className="block w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground" onClick={() => { setOpen(false); onSelect("stt", "dyna", model); }}>{label}</button>)}
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
  triggerTerms = [],
}: {
  segment: TranscriptSegment;
  onSeek: (ms: number) => void;
  flash?: boolean;
  innerRef?: (el: HTMLButtonElement | null) => void;
  triggerTerms?: string[];
}) {
  const role = segment.channel_role;
  const isBroker = role === "broker";
  const isCustomer = role === "customer";
  const mixed = !isBroker && !isCustomer;
  const ranges = knowledgeTriggerRanges(segment.text, triggerTerms);
  const riskTerm = isCustomer ? complaintTrigger(segment.text) : null;
  const highlighted: React.ReactNode[] = [];
  let cursor = 0;
  const riskRanges = riskTerm ? knowledgeTriggerRanges(segment.text, [riskTerm]) : [];
  const allRanges = [...ranges.filter(([start, end]) => !riskRanges.some(([a, b]) => start < b && end > a)), ...riskRanges].sort((a, b) => a[0] - b[0]);
  for (const [start, end] of allRanges) {
    highlighted.push(segment.text.slice(cursor, start));
    highlighted.push(<mark key={start} className={cn("rounded-sm px-0.5 font-semibold", riskRanges.some(([a]) => a === start) ? "bg-red-200 text-red-950 dark:bg-red-500/30 dark:text-red-100" : "bg-amber-200 text-amber-950 dark:bg-amber-400/30 dark:text-amber-100")}>{segment.text.slice(start, end)}</mark>);
    cursor = end;
  }
  highlighted.push(segment.text.slice(cursor));

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
        </span>
        <span className="block whitespace-pre-wrap">{highlighted}</span>
      </button>
    </div>
  );
}

export function RecordingDetailView({
  recordingId,
  projectId,
  canManage,
  crsOnly = false,
  canReview,
}: {
  recordingId: string;
  projectId: string;
  canManage: boolean;
  crsOnly?: boolean;
  canReview: boolean;
}) {
  const [rec, setRec] = React.useState<RecordingDetail | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [transcript, setTranscript] = React.useState<Transcript | null>(null);
  const [transcriptMissing, setTranscriptMissing] = React.useState(false);
  const [transcriptError, setTranscriptError] = React.useState<string | null>(null);
  const [transcriptOpen, setTranscriptOpen] = React.useState(false);
  const [showRaw, setShowRaw] = React.useState(false);
  const [reprocessing, setReprocessing] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [flashIdx, setFlashIdx] = React.useState<number | null>(null);
  const [selectedKnowledgeCard, setSelectedKnowledgeCard] = React.useState<KnowledgeCard | null>(null);
  const [currentMs, setCurrentMs] = React.useState(0);
  const [playing, setPlaying] = React.useState(false);
  const [replayTranscript, setReplayTranscript] = React.useState(false);
  const [editTarget, setEditTarget] = React.useState<{ segment: TranscriptSegment; hotword: boolean; selection: string } | null>(null);
  const supervisor = useSupervisorContact(projectId);

  const recRef = React.useRef<RecordingDetail | null>(null);
  const audioRef = React.useRef<HTMLAudioElement>(null);
  const segmentRefs = React.useRef(new Map<number, HTMLButtonElement>());
  const transcriptScrollRef = React.useRef<HTMLDivElement>(null);
  const visibleReplayCount = transcript?.segments.filter((segment) => segment.start_ms <= currentMs).length ?? 0;
  React.useEffect(() => {
    const element = transcriptScrollRef.current;
    if (element && replayTranscript && playing && !selectedKnowledgeCard) element.scrollTop = element.scrollHeight;
  }, [visibleReplayCount, replayTranscript, playing, selectedKnowledgeCard]);
  const flashTimer = React.useRef<number | null>(null);
  const pendingEvidenceIdx = React.useRef<number | null>(null);

  const loadRecording = React.useCallback(async () => {
    try {
      const r = await apiCall("/api/recordings/{recording_id}", "get", {
        params: { path: { recording_id: recordingId }, query: { project_id: projectId } },
      });
      recRef.current = r;
      setRec(r);
      setLoadError(null);
    } catch (e) {
      if (recRef.current === null) setLoadError(getApiErrorMessage(e));
    }
  }, [projectId, recordingId]);

  const loadTranscript = React.useCallback(async () => {
    try {
      const t = await apiCall("/api/recordings/{recording_id}/transcript", "get", {
        params: { path: { recording_id: recordingId }, query: { project_id: projectId } },
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
  }, [projectId, recordingId]);

  React.useEffect(() => {
    void loadRecording();
    void loadTranscript();
  }, [loadRecording, loadTranscript]);

  React.useEffect(() => {
    setTranscriptOpen(false);
    setShowRaw(false);
    pendingEvidenceIdx.current = null;
    setSelectedKnowledgeCard(null);
    setEditTarget(null);
    setCurrentMs(0);
    setPlaying(false);
    setReplayTranscript(false);
  }, [recordingId, projectId]);

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
    pendingEvidenceIdx.current = idx;
    if (transcriptOpen) {
      window.requestAnimationFrame(() => {
        segmentRefs.current.get(idx)?.scrollIntoView({ behavior: "smooth", block: "center" });
        pendingEvidenceIdx.current = null;
      });
    } else {
      setTranscriptOpen(true);
    }
    setFlashIdx(idx);
    if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlashIdx(null), 1600);
  }

  React.useEffect(() => {
    if (!transcriptOpen || pendingEvidenceIdx.current === null) return;
    const idx = pendingEvidenceIdx.current;
    const frame = window.requestAnimationFrame(() => {
      segmentRefs.current.get(idx)?.scrollIntoView({ behavior: "smooth", block: "center" });
      pendingEvidenceIdx.current = null;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [transcriptOpen]);

  React.useEffect(
    () => () => {
      if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    },
    [],
  );

  async function onReprocess(fromStage: "convert" | "stt", provider?: string, model?: string) {
    setActionError(null);
    setNotice(null);
    setReprocessing(true);
    try {
      await apiCall("/api/recordings/{recording_id}/reprocess", "post", {
        params: {
          path: { recording_id: recordingId },
          query: { from_stage: fromStage, project_id: projectId, asr_provider: provider, asr_model: model },
        },
      });
      setNotice(`Reprocess queued (from ${fromStage}).`);
      await loadRecording();
    } catch (e) {
      setActionError(getApiErrorMessage(e));
    } finally {
      setReprocessing(false);
    }
  }

  async function downloadTranscript(format: "full" | "segments") {
    setActionError(null);
    try {
      const query = new URLSearchParams({ project_id: projectId, format });
      const response = await fetch(
        `${API_URL}/api/recordings/${recordingId}/transcript/export?${query.toString()}`,
        { credentials: "include" },
      );
      if (!response.ok) throw new Error(`Transcript export failed (HTTP ${response.status})`);
      const blob = await response.blob();
      const disposition = response.headers.get("content-disposition") ?? "";
      const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? `transcript-${format}.txt`;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Transcript export failed.");
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

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Call details</CardTitle>
          </CardHeader>
          <CardContent>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
                <MetaItem label="Agent" source="filename">
                  {[rec.broker_ext, rec.broker_name].filter(Boolean).join(" / ") || "--"}
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
              src={`${API_URL}/api/recordings/${recordingId}/audio?project_id=${encodeURIComponent(projectId)}`}
              className="w-full"
              onTimeUpdate={(event) => setCurrentMs(Math.round(event.currentTarget.currentTime * 1000))}
              onPlay={() => { setPlaying(true); if (transcript?.knowledge_cards?.length) setTranscriptOpen(true); }}
              onPause={() => setPlaying(false)}
              onEnded={() => setPlaying(false)}
            />
          </CardContent>
        </Card>
      </div>

      {!crsOnly && rec.processing_mode !== "transcription_only" && (
        <EvaluationPanel
          recordingId={recordingId}
          projectId={projectId}
          recordingStatus={rec.status}
          canReview={canReview}
          onJump={jumpToEvidence}
          onRecordingChanged={() => void loadRecording()}
        />
      )}

      <Card>
        <CardHeader className="p-0">
          <button
            type="button"
            className="flex w-full items-start justify-between gap-4 rounded-lg p-6 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            onClick={() => setTranscriptOpen((open) => !open)}
            aria-expanded={transcriptOpen}
            aria-controls="recording-transcript"
          >
            <div>
              <CardTitle className="text-base">Transcript</CardTitle>
              <CardDescription className="mt-1">
                {transcript
                  ? `${transcript.transcribed_at ? `${formatDateTime(transcript.transcribed_at)} · ` : ""}Transcribed`
                  : transcriptMissing
                    ? "No transcript available"
                    : "Expand to view the transcription"}
              </CardDescription>
            </div>
            <ChevronDown
              className={cn(
                "mt-0.5 h-5 w-5 shrink-0 text-muted-foreground transition-transform",
                transcriptOpen && "rotate-180",
              )}
              aria-hidden
            />
          </button>
        </CardHeader>
        {transcriptOpen && (
          <CardContent id="recording-transcript" className="border-t pt-6">
            {transcript && transcript.full_text && (
              <div className="mb-4 flex flex-wrap justify-end gap-2">
                <Button variant="outline" size="sm" onClick={() => void downloadTranscript("full")}>
                  <Download className="mr-2 h-4 w-4" aria-hidden />
                  Full transcript
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void downloadTranscript("segments")}
                >
                  <Download className="mr-2 h-4 w-4" aria-hidden />
                  Segmented file
                </Button>
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={replayTranscript} onChange={(e) => { setReplayTranscript(e.target.checked); setShowRaw(false); if (audioRef.current) { audioRef.current.pause(); audioRef.current.currentTime = 0; } setCurrentMs(0); }} />錄音逐句回放</label>
                <Button disabled={replayTranscript} variant="ghost" size="sm" onClick={() => setShowRaw((v) => !v)}>
                  {showRaw ? "Hide raw text" : "Show raw text"}
                </Button>
              </div>
            )}
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
                {transcript.edited_at && <p className="text-xs text-amber-700 dark:text-amber-300">{formatDateTime(transcript.edited_at)} · 人工修訂。分析結果請以修訂後重新執行的版本為準。</p>}
                {!replayTranscript && transcript.audio_reviews && transcript.audio_reviews.length > 0 && (
                  <section className="space-y-3 border-b pb-4">
                    <h3 className="text-sm font-semibold">Audio review</h3>
                    {transcript.audio_reviews.map((review, index) => (
                      <div key={index} className="space-y-1 border-l-2 border-amber-400 pl-3 text-sm">
                        <div className="flex items-center gap-3">
                          <Button variant="ghost" size="sm" onClick={() => seekTo(review.start_ms)}>
                            {Math.floor(review.start_ms / 60000)}:{String(Math.floor(review.start_ms / 1000) % 60).padStart(2, "0")}
                          </Button>
                          <span>{review.status === "needs_review" ? "Needs review" : review.status === "confirmed" ? "Confirmed" : "Review unavailable"}</span>
                        </div>
                        <p><span className="text-muted-foreground">Original: </span>{review.original_text}</p>
                        {review.suggested_text && <p><span className="text-muted-foreground">Audio suggestion: </span>{review.suggested_text}</p>}
                        {review.reason === "numeric_conflict" && <p className="text-amber-700">Number conflict; original retained.</p>}
                        {review.reason === "uncertain" && <p className="text-amber-700">Audio unclear; original retained.</p>}
                      </div>
                    ))}
                  </section>
                )}
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
                  <div ref={transcriptScrollRef} className="max-h-[36rem] space-y-2 overflow-y-auto pr-1" aria-live={replayTranscript ? "polite" : "off"}>
                    {replayTranscript && currentMs === 0 && <p className="p-3 text-sm text-muted-foreground">等待錄音播放…</p>}
                    {transcript.segments.map((s, i) => (!replayTranscript || s.start_ms <= currentMs) && (
                      <div key={i} className="space-y-1">
                      <SegmentBubble
                        segment={s}
                        triggerTerms={(transcript.knowledge_cards ?? []).flatMap((match) => match.hits.filter((hit) => hit.segment_index === i).flatMap((hit) => hit.matched_terms))}
                        onSeek={seekTo}
                        flash={flashIdx === i}
                        innerRef={(el) => {
                          if (el) segmentRefs.current.set(i, el);
                          else segmentRefs.current.delete(i);
                        }}
                      />
                      {canReview && s.id && <div className={cn("flex gap-1", s.channel_role === "customer" && "justify-end")}>
                        <Button size="icon" variant="ghost" className="h-7 w-7" disabled={busy} title="修改此句轉寫" aria-label="修改此句轉寫" onClick={() => setEditTarget({ segment: s, hotword: false, selection: "" })}><Pencil className="h-3.5 w-3.5" /></Button>
                        {canManage && <Button size="icon" variant="ghost" className="h-7 w-7" disabled={busy} title="提交熱詞標註" aria-label="提交熱詞標註" onMouseDown={(event) => event.preventDefault()} onClick={() => setEditTarget({ segment: s, hotword: true, selection: window.getSelection()?.toString().trim() ?? "" })}><Tag className="h-3.5 w-3.5" /></Button>}
                      </div>}
                      <div className={cn("flex", s.channel_role === "customer" && "justify-end")}>
                        {s.channel_role === "customer" && complaintTrigger(s.text) && <SupervisorAlert key={`${projectId}:${recordingId}:${i}`} active={s.start_ms <= currentMs} contact={supervisor.contact} error={supervisor.error} />}
                      </div>
                      <div className={cn("flex", s.channel_role === "customer" && "justify-end")}>
                        <TranscriptKnowledgeHints matches={(transcript.knowledge_cards ?? []).filter((match) => match.hits.some((hit) => hit.segment_index === i))} onSelect={setSelectedKnowledgeCard} />
                      </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        )}
      </Card>
      <KnowledgeCardDialog projectId={projectId} card={selectedKnowledgeCard} onClose={() => setSelectedKnowledgeCard(null)} />
      {editTarget && <TranscriptEditor key={`${editTarget.segment.id}:${editTarget.hotword}`} projectId={projectId} recordingId={recordingId} {...editTarget} canTerms={canManage} onClose={() => setEditTarget(null)} onSaved={async (changed, hotword) => { await loadTranscript(); setNotice(hotword ? "已提交項目熱詞標註。Dyna 平台詞庫需另行同步。" : changed ? "轉寫已儲存，請重新執行 CRS／evaluation。" : "文字沒有變更。"); }} />}
      {crsOnly && <CrsPanel projectId={projectId} recordingId={recordingId} recordingStatus={rec.status} canRun={canReview} transcriptEditedAt={transcript?.edited_at} onChanged={() => void loadRecording()} />}
    </div>
  );
}
