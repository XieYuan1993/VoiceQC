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
  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose(); }}><DialogContent className="max-w-2xl"><DialogHeader><DialogTitle>{hotword ? "Submit hotword" : "Edit transcript"} · {formatMs(segment.start_ms)}</DialogTitle></DialogHeader><form className="space-y-4" onSubmit={save}>
    <label className="block space-y-1 text-sm"><span>Transcript text</span><textarea className={input} rows={5} required maxLength={20000} value={text} disabled={busy} onChange={(e) => setText(e.target.value)} /></label>
    {canTerms && <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={busy} checked={includeWord} onChange={(e) => setIncludeWord(e.target.checked)} />Submit a project hotword and correction annotation</label>}
    {includeWord && <fieldset disabled={busy} className="space-y-3 border-t pt-3"><div className="grid gap-3 sm:grid-cols-2"><label className="block space-y-1 text-sm"><span>Incorrect word in this segment (optional)</span><input className={input} maxLength={200} value={wrong} onChange={(e) => setWrong(e.target.value)} /></label><label className="block space-y-1 text-sm"><span>Correct hotword</span><input className={input} required maxLength={200} value={correct} onChange={(e) => setCorrect(e.target.value)} /></label></div><label className="block space-y-1 text-sm"><span>Type</span><select className={input} value={category} onChange={(e) => setCategory(e.target.value)}><option value="jargon">Business term</option><option value="person">Person name</option><option value="other">Other</option></select></label><label className="block space-y-1 text-sm"><span>Context / notes</span><textarea className={input} rows={2} maxLength={1000} value={context} onChange={(e) => setContext(e.target.value)} /></label></fieldset>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}<div className="flex justify-end gap-2"><Button type="button" variant="outline" disabled={busy} onClick={onClose}>Cancel</Button><Button type="submit" disabled={busy || !text.trim() || (includeWord && !correct.trim())}>{busy ? "Saving..." : "Save / submit"}</Button></div>
  </form></DialogContent></Dialog>;
}
