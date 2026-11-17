"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { apiJson, getApiErrorMessage } from "@/lib/api";
import { menuOptions, menuVisible } from "@/lib/navigation";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

export function NavigationSettings({ projectId, canManage }: { projectId: string; canManage: boolean }) {
  const router = useRouter();
  const [value, setValue] = React.useState<Record<string, boolean>>({});
  const [loaded, setLoaded] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState("");
  React.useEffect(() => {
    let active = true;
    apiJson<Record<string, boolean>>("/api/settings/navigation", "get", { params: { query: { project_id: projectId } } })
      .then((data) => { if (active) { setValue(data); setLoaded(true); } })
      .catch((error) => { if (active) setMessage(getApiErrorMessage(error)); });
    return () => { active = false; };
  }, [projectId]);
  async function save() {
    setBusy(true); setMessage("");
    try {
      await apiJson("/api/settings/ui.navigation", "put", { params: { query: { project_id: projectId } }, body: { value } });
      window.dispatchEvent(new Event("navigation-settings-changed"));
      router.refresh(); setMessage("Menu visibility saved.");
    } catch (error) { setMessage(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }
  return <section className="space-y-4 border-t pt-5"><h2 className="font-semibold">Menu visibility</h2>
    <fieldset disabled={!canManage || !loaded || busy} className="grid max-w-3xl gap-x-8 sm:grid-cols-2">
      {menuOptions.map(([path, label]) => <label key={path} className="flex items-center justify-between gap-4 border-b py-3 text-sm"><span>{label}</span><Switch checked={menuVisible(path, value)} onCheckedChange={(checked) => setValue({ ...value, [path]: checked })} /></label>)}
    </fieldset>
    {canManage && <Button disabled={!loaded || busy} onClick={() => void save()}>{busy ? "Saving..." : "Save"}</Button>}
    {message && <p role="status" className="text-sm">{message}</p>}
  </section>;
}
