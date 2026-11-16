"use client";
import * as React from "react";
import { BellRing } from "lucide-react";
import { apiJson } from "@/lib/api";
import type { SupervisorContact } from "@/lib/supervisor-notification";

export function useSupervisorContact(projectId: string) {
  const [contact, setContact] = React.useState<SupervisorContact | null>(null);
  const [error, setError] = React.useState(false);
  React.useEffect(() => {
    const controller = new AbortController();
    setContact(null); setError(false);
    apiJson<SupervisorContact>("/api/settings/supervisor-notification", "get", { params: { query: { project_id: projectId } }, signal: controller.signal }).then(setContact).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [projectId]);
  return { contact, error };
}

export function SupervisorAlert({ active, contact, error }: { active: boolean; contact: SupervisorContact | null; error: boolean }) {
  const [notified, setNotified] = React.useState(false);
  const channels = [contact?.email_enabled && contact.email ? `Email：${contact.email}` : "", contact?.sms_enabled && contact.phone ? `SMS：${contact.phone}` : ""].filter(Boolean);
  React.useEffect(() => { if (active && channels.length && !error) setNotified(true); }, [active, channels.length, error]);
  return <div role="status" className="max-w-lg rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-950 dark:border-red-800 dark:bg-red-950/40 dark:text-red-100">
    <span className="flex items-center gap-2 font-medium"><BellRing className="h-3.5 w-3.5 shrink-0" aria-hidden />{notified ? "已自動通知主管（演示）" : "客戶投訴／強烈不滿 · 主管升級提示"}</span>
    <p className="mt-1 break-words">{notified ? `${contact?.name || "主管"} · ${channels.join("；")} · 未實際發送` : !active ? "到達此時間點後自動通知" : error ? "設定載入失敗，未通知" : !contact ? "載入通知設定中…" : "未啟用通知渠道，請在 Settings → 主管通知設定"}</p>
  </div>;
}
