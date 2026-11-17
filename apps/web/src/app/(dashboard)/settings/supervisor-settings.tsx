"use client";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { apiJson } from "@/lib/api";
import { emptySupervisor, type SupervisorContact } from "@/lib/supervisor-notification";

export function SupervisorSettings({ projectId, canManage }: { projectId: string; canManage: boolean }) {
  const [value, setValue] = React.useState<SupervisorContact>(emptySupervisor);
  const [loaded, setLoaded] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const load = React.useCallback(() => {
    setLoaded(false); setMessage("");
    apiJson<SupervisorContact>("/api/settings/supervisor-notification", "get", { params: { query: { project_id: projectId } } }).then((data) => { setValue(data); setLoaded(true); }).catch(() => setMessage("Unable to load supervisor settings."));
  }, [projectId]);
  React.useEffect(load, [load]);
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setMessage("");
    try { await apiJson("/api/settings/notification.supervisor", "put", { params: { query: { project_id: projectId } }, body: { value } }); setMessage("Saved"); }
    catch { setMessage("Unable to save. Check the contact details for each enabled channel."); }
    finally { setBusy(false); }
  }
  return <section className="space-y-4 border-t pt-5"><h2 className="text-base font-semibold">Supervisor notifications</h2><p className="text-xs text-muted-foreground">Demo mode - no email or SMS will be sent</p>
    <form onSubmit={save} className="max-w-xl space-y-4"><fieldset disabled={!canManage || !loaded || busy} className="space-y-4">
      <label className="block space-y-1 text-sm"><span>Supervisor name</span><input className="w-full rounded-md border bg-background p-2" maxLength={254} value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} /></label>
      {([['email_enabled', 'email', 'Email', 'Supervisor email'], ['sms_enabled', 'phone', 'SMS', 'Supervisor phone (including country code)']] as const).map(([enabled, field, title, label]) => <div key={field} className="space-y-2"><label className="flex items-center gap-2 text-sm">{title}<Switch checked={value[enabled]} onCheckedChange={(checked) => setValue({ ...value, [enabled]: checked })} /></label><label className="block space-y-1 text-sm"><span>{label}</span><input className="w-full rounded-md border bg-background p-2" type={field === 'email' ? 'email' : 'tel'} required={value[enabled]} maxLength={254} value={value[field]} onChange={(e) => setValue({ ...value, [field]: e.target.value.trim() })} /></label></div>)}
      {canManage && <Button type="submit">{busy ? "Saving..." : "Save"}</Button>}
    </fieldset></form>{message && <p role="status" className="text-sm">{message}</p>}{!loaded && message && <Button variant="outline" onClick={load}>Retry</Button>}
  </section>;
}
