"use client";
import * as React from "react";
import { BellRing } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { apiJson } from "@/lib/api";
import { complaintTrigger, type SupervisorContact } from "@/lib/supervisor-notification";
import type { TranscriptSegment } from "@/lib/types";

export function SupervisorAlert({ projectId, segments, currentMs, playing, blocked }: { projectId: string; segments: TranscriptSegment[]; currentMs: number; playing: boolean; blocked: boolean }) {
  const [contact, setContact] = React.useState<SupervisorContact | null>(null);
  const [error, setError] = React.useState(false);
  const [open, setOpen] = React.useState(false);
  const [prompted, setPrompted] = React.useState(false);
  const [notified, setNotified] = React.useState(false);
  const [sentVia, setSentVia] = React.useState("");
  const hit = segments.find((segment) => segment.channel_role === "customer" && segment.start_ms <= currentMs && complaintTrigger(segment.text));
  const load = React.useCallback(() => {
    setError(false);
    apiJson<SupervisorContact>("/api/settings/supervisor-notification", "get", { params: { query: { project_id: projectId } } }).then(setContact).catch(() => setError(true));
  }, [projectId]);
  React.useEffect(load, [load]);
  React.useEffect(() => {
    if (playing && hit && !blocked && !prompted) { setOpen(true); setPrompted(true); }
  }, [playing, hit, blocked, prompted]);
  const channels = [contact?.email_enabled && contact.email ? `Email：${contact.email}` : "", contact?.sms_enabled && contact.phone ? `SMS：${contact.phone}` : ""].filter(Boolean);
  if (!hit) return null;
  return <section className="space-y-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-950 dark:border-red-800 dark:bg-red-950/30 dark:text-red-100">
    <div className="flex flex-wrap items-center justify-between gap-2"><span className="flex items-center gap-2 font-medium"><BellRing className="h-4 w-4" />{notified ? "已通知主管（演示）" : "偵測到客戶強烈不滿／投訴"}</span>{!notified && <Button size="sm" variant="outline" onClick={() => { load(); setOpen(true); }}>通知主管</Button>}</div>
    {notified && <p className="break-words text-xs">{sentVia} · 未實際發送</p>}
    <Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogHeader><DialogTitle>是否通知主管？</DialogTitle></DialogHeader>
      <p className="text-sm">客戶可能需要升級處理。</p><blockquote className="max-h-32 overflow-y-auto border-l-2 border-red-400 pl-3 text-sm">{hit.text}</blockquote>
      <p className="text-sm font-medium">{contact?.name || "主管"}</p>
      {channels.map((channel) => <p key={channel} className="break-words text-sm">{channel}</p>)}
      {error ? <p role="alert" className="text-sm text-destructive">無法讀取主管設定。<button className="ml-2 underline" onClick={load}>重試</button></p> : !contact ? <p className="text-sm">載入設定中…</p> : !channels.length && <p className="text-sm text-destructive">尚未啟用通知渠道，請先在 Settings → 主管通知中設定。</p>}
      <p className="text-xs text-muted-foreground">演示模式 · 不會實際發送郵件或 SMS</p>
      <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setOpen(false)}>暫不通知</Button><Button disabled={!channels.length || error || !contact} onClick={() => { setSentVia(channels.join("；")); setNotified(true); setOpen(false); }}>通知主管</Button></div>
    </DialogContent></Dialog>
  </section>;
}
