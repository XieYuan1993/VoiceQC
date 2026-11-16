"use client";
import * as React from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, ArrowRight, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiJson } from "@/lib/api";
import { formatDateTime, formatMs } from "@/lib/format";
import { knowledgeTriggerRanges } from "@/lib/knowledge-trigger-highlights";

type Hit = { trigger: string; risk_type: string; label: string; text: string; start_ms: number };
type Result = { total: number; page_size: number; items: { recording_id: string; filename: string; call_started_at: string | null; status: string; hits: Hit[] }[] };
function Evidence({ hit }: { hit: Hit }) {
  const ranges = knowledgeTriggerRanges(hit.text, [hit.trigger]);
  let cursor = 0;
  const pieces: React.ReactNode[] = [];
  for (const [a, b] of ranges) { pieces.push(hit.text.slice(cursor, a)); pieces.push(<mark key={a} className="rounded-sm bg-red-200 px-0.5 font-medium text-red-950 dark:bg-red-500/30 dark:text-red-100">{hit.text.slice(a, b)}</mark>); cursor = b; }
  pieces.push(hit.text.slice(cursor));
  return <p className="whitespace-pre-wrap break-words leading-relaxed">{pieces}</p>;
}
export function RiskInbox({ projectId }: { projectId: string }) {
  const [result, setResult] = React.useState<Result | null>(null);
  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [kind, setKind] = React.useState("");
  const [refresh, setRefresh] = React.useState(0);
  const [error, setError] = React.useState(false);
  React.useEffect(() => {
    const controller = new AbortController();
    setResult(null); setError(false);
    apiJson<Result>("/api/risks", "get", { params: { query: { project_id: projectId, page, q, kind: kind || undefined } }, signal: controller.signal }).then(setResult).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [projectId, page, q, kind, refresh]);
  return <div className="space-y-5">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="flex items-center gap-2 text-2xl font-semibold"><AlertTriangle className="h-6 w-6 text-red-600" />風險錄音</h1><p className="mt-1 text-sm text-muted-foreground">投訴升級 · 強烈不滿 · 要求主管介入{result && ` · ${result.total} 通錄音`}</p></div><Button variant="outline" size="icon" aria-label="刷新" title="刷新" onClick={() => setRefresh((value) => value + 1)}><RefreshCw className="h-4 w-4" /></Button></header>
    <div className="flex flex-wrap gap-3 border-b pb-4"><input aria-label="搜尋錄音名稱" placeholder="搜尋錄音名稱" className="w-full max-w-sm rounded-md border bg-background px-3 py-2 text-sm" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /><select aria-label="風險類型" className="rounded-md border bg-background px-3 py-2 text-sm" value={kind} onChange={(e) => { setKind(e.target.value); setPage(1); }}><option value="">所有風險類型</option><option value="complaint">投訴升級</option><option value="dissatisfaction">強烈不滿</option><option value="supervisor">要求主管介入</option></select></div>
    {error ? <p role="alert" className="text-sm text-destructive">無法載入風險錄音，請重新整理或確認權限。</p> : !result ? <p role="status" className="text-sm text-muted-foreground">載入中…</p> : !result.items.length ? <p className="py-8 text-sm text-muted-foreground">沒有符合條件的風險錄音</p> : <div className="divide-y">{result.items.map((item) => <section key={item.recording_id} className="py-4 first:pt-0"><div className="flex flex-wrap items-center justify-between gap-2"><Link className="break-all font-medium text-primary hover:underline" href={`/recordings/${item.recording_id}` as never}>{item.filename}</Link><span className="text-xs text-muted-foreground">{item.call_started_at ? formatDateTime(item.call_started_at) : "—"} · {item.hits.length} 個提示</span></div><div className="mt-3 space-y-3">{item.hits.map((hit, index) => <div key={index} className="border-l-2 border-red-400 pl-3 text-sm"><div className="mb-1 flex flex-wrap items-center gap-3 text-xs"><strong className="text-red-700 dark:text-red-300">{hit.label}</strong><span className="tabular-nums text-muted-foreground">{formatMs(hit.start_ms)} · Customer</span></div><Evidence hit={hit} /></div>)}</div></section>)}</div>}
    {result && <footer className="flex items-center justify-end gap-3 border-t pt-3 text-sm"><Button variant="outline" size="icon" aria-label="上一頁" disabled={page <= 1} onClick={() => setPage(page - 1)}><ArrowLeft className="h-4 w-4" /></Button><span>{page} / {Math.max(1, Math.ceil(result.total / result.page_size))}</span><Button variant="outline" size="icon" aria-label="下一頁" disabled={page * result.page_size >= result.total} onClick={() => setPage(page + 1)}><ArrowRight className="h-4 w-4" /></Button></footer>}
  </div>;
}
