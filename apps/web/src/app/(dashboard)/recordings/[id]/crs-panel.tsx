"use client";
import * as React from "react";
import { RotateCw } from "lucide-react";
import { apiJson } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";

type CrsEvent = { enquiry: string; category: string; event_detail: string; content_detail: string; reason: string; rationale: string; evidence_quote: string; needs_review: boolean; evidence_verified: boolean };
type Run = { id: string; run_seq: number; status: string; completed_at: string | null; extracted_call_fields: { crs?: { mode: string; source: string; events: CrsEvent[] } } };

export function CrsPanel({ projectId, recordingId, recordingStatus, canRun, onChanged, transcriptEditedAt }: { projectId: string; recordingId: string; recordingStatus: string; canRun: boolean; onChanged: () => void; transcriptEditedAt?: string | null }) {
  const [runs, setRuns] = React.useState<Run[]>([]);
  const [selected, setSelected] = React.useState("");
  const [error, setError] = React.useState("");
  const [loaded, setLoaded] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [queued, setQueued] = React.useState(false);
  const busy = queued || ["uploaded", "converting", "transcribing", "evaluating"].includes(recordingStatus);
  const load = React.useCallback(async () => {
    const data = await apiJson<Run[]>(`/api/recordings/${recordingId}/evaluations`, "get", { params: { query: { project_id: projectId } } });
    setRuns(data.filter((run) => run.extracted_call_fields?.crs?.mode === "crs_classification")); setLoaded(true); setError("");
  }, [projectId, recordingId]);
  React.useEffect(() => { load().catch(() => setError("無法載入 CRS 分類。")); }, [load, recordingStatus]);
  React.useEffect(() => { if (recordingStatus === "evaluating" || recordingStatus === "failed") setQueued(false); }, [recordingStatus]);
  async function run() {
    setSubmitting(true); setError("");
    try { await apiJson(`/api/recordings/${recordingId}/evaluations`, "post", { params: { query: { project_id: projectId } } }); setQueued(true); onChanged(); }
    catch { setError("未能啟動 CRS 分類，請確認錄音轉寫已完成且目前沒有其他任務。"); }
    finally { setSubmitting(false); }
  }
  const evaluation = runs.find((value) => value.id === selected) ?? runs[0];
  return <section className="space-y-4 border-t pt-5"><header className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-base font-semibold">CRS 業務分類</h2>{evaluation?.completed_at && <p className="text-xs text-muted-foreground">{formatDateTime(evaluation.completed_at)} · Classified</p>}</div><div className="flex flex-wrap gap-2">{runs.length > 1 && <select aria-label="CRS 分類版本" className="rounded-md border bg-background px-2 text-sm" value={evaluation?.id} onChange={(e) => setSelected(e.target.value)}>{runs.map((value) => <option key={value.id} value={value.id}>Run #{value.run_seq}</option>)}</select>}{canRun && <Button variant="outline" size="sm" disabled={busy || submitting} onClick={() => void run()}><RotateCw className="mr-2 h-4 w-4" />{busy ? "分類處理中…" : submitting ? "提交中…" : "重新分類"}</Button>}</div></header>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {evaluation?.completed_at && transcriptEditedAt && new Date(transcriptEditedAt) > new Date(evaluation.completed_at) && <p role="status" className="text-sm text-amber-700 dark:text-amber-300">轉寫已在此分類之後修訂，請重新分類。</p>}
    {!loaded && !error ? <p className="text-sm text-muted-foreground">載入中…</p> : !evaluation ? <p className="text-sm text-muted-foreground">{busy ? "CRS 分類處理中…" : "尚未有 CRS 分類結果"}</p> : <div className="divide-y">{evaluation.extracted_call_fields.crs?.events.map((event, index) => <article key={index} className="space-y-3 py-4 first:pt-0"><div className="flex flex-wrap gap-2"><h3 className="font-medium">Enquiry {index + 1} · {event.enquiry}</h3>{event.needs_review && <span className="text-xs text-amber-700 dark:text-amber-300">待確認</span>}</div><dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">{[["CRS 分類", event.category], ["CRS 事件明細", event.event_detail], ["CRS 內容明細", event.content_detail], ["Reason", event.reason]].map(([label, value]) => <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-words">{value}</dd></div>)}</dl><div className="text-sm"><h4 className="text-xs text-muted-foreground">分類依據</h4><p className="mt-1 whitespace-pre-wrap break-words">{event.rationale}</p></div><blockquote className="whitespace-pre-wrap break-words border-l-2 pl-3 text-sm text-muted-foreground">{event.evidence_quote}</blockquote>{!event.evidence_verified && <p className="text-xs text-amber-700">引文未能逐字核對，請人工確認。</p>}</article>)}</div>}
  </section>;
}
