"use client";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { apiJson, getApiErrorMessage } from "@/lib/api";
import type { TranscriptSegment } from "@/lib/types";
import { formatMs } from "@/lib/format";

export function TranscriptEditor({ projectId, recordingId, segment, hotword, selection, canTerms, onClose, onSaved }: { projectId: string; recordingId: string; segment: TranscriptSegment; hotword: boolean; selection: string; canTerms: boolean; onClose: () => void; onSaved: (changed: boolean, hotword: boolean) => Promise<void> }) {
  const [text, setText] = React.useState(segment.text);
  const [includeWord, setIncludeWord] = React.useState(hotword);
  const [wrong, setWrong] = React.useState(selection && segment.text.includes(selection) ? selection : "");
  const [correct, setCorrect] = React.useState("");
  const [category, setCategory] = React.useState("jargon");
  const [context, setContext] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const input = "w-full rounded-md border bg-background px-3 py-2 text-sm";
  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await apiJson<{ changed: boolean; hotword_saved: boolean }>(`/api/recordings/${recordingId}/transcript/segments/${segment.id}`, "patch", { params: { query: { project_id: projectId } }, body: { expected_text: segment.text, text, ...(includeWord ? { wrong, correct, category, context } : {}) } });
      await onSaved(result.changed, result.hotword_saved);
      onClose();
    } catch (err) { setError(getApiErrorMessage(err)); }
    finally { setBusy(false); }
  }
  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose(); }}><DialogContent className="max-w-2xl"><DialogHeader><DialogTitle>{hotword ? "提交熱詞標註" : "修改轉寫"} · {formatMs(segment.start_ms)}</DialogTitle></DialogHeader><form className="space-y-4" onSubmit={save}>
    <label className="block space-y-1 text-sm"><span>轉寫文字</span><textarea className={input} rows={5} required maxLength={20000} value={text} disabled={busy} onChange={(e) => setText(e.target.value)} /></label>
    {canTerms && <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={busy} checked={includeWord} onChange={(e) => setIncludeWord(e.target.checked)} />提交項目熱詞及錯誤→正確標註</label>}
    {includeWord && <fieldset disabled={busy} className="space-y-3 border-t pt-3"><div className="grid gap-3 sm:grid-cols-2"><label className="block space-y-1 text-sm"><span>原句中的錯誤詞（選填）</span><input className={input} maxLength={200} value={wrong} onChange={(e) => setWrong(e.target.value)} /></label><label className="block space-y-1 text-sm"><span>正確熱詞</span><input className={input} required maxLength={200} value={correct} onChange={(e) => setCorrect(e.target.value)} /></label></div><label className="block space-y-1 text-sm"><span>類型</span><select className={input} value={category} onChange={(e) => setCategory(e.target.value)}><option value="jargon">業務術語</option><option value="person">人名</option><option value="other">其他</option></select></label><label className="block space-y-1 text-sm"><span>適用上下文／備註</span><textarea className={input} rows={2} maxLength={1000} value={context} onChange={(e) => setContext(e.target.value)} /></label></fieldset>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}<div className="flex justify-end gap-2"><Button type="button" variant="outline" disabled={busy} onClick={onClose}>取消</Button><Button type="submit" disabled={busy || !text.trim() || (includeWord && !correct.trim())}>{busy ? "儲存中…" : "儲存／提交"}</Button></div>
  </form></DialogContent></Dialog>;
}
