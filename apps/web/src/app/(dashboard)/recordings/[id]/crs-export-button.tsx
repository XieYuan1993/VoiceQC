"use client";

import * as React from "react";
import { Download, Loader2 } from "lucide-react";
import { API_URL, ApiError, getApiErrorMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function CrsExportButton({ projectId, evaluationId, enabled }: {
  projectId: string; evaluationId?: string; enabled: boolean;
}) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  React.useEffect(() => { setError(""); }, [projectId, evaluationId]);
  async function download() {
    if (!evaluationId) return;
    setBusy(true); setError("");
    try {
      const query = new URLSearchParams({ project_id: projectId });
      const response = await fetch(`${API_URL}/api/evaluations/${evaluationId}/export?${query}`, {
        credentials: "include", cache: "no-store",
      });
      if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => null));
      const blob = await response.blob();
      const filename = response.headers.get("content-disposition")?.match(/filename="([^"]+)"/)?.[1]
        ?? `crs_${evaluationId}.json`;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = filename; anchor.hidden = true;
      document.body.appendChild(anchor);
      try { anchor.click(); } finally { anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
    } catch (error) { setError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }
  return <div className="space-y-1">
    <Button variant="outline" size="sm" disabled={!enabled || !evaluationId || busy} onClick={() => void download()}>
      {busy ? <Loader2 aria-hidden className="mr-2 h-4 w-4 animate-spin" /> : <Download aria-hidden className="mr-2 h-4 w-4" />}
      {busy ? "Exporting..." : "Export JSON"}
    </Button>
    {error && <p role="alert" className="max-w-sm break-words text-xs text-destructive">{error}</p>}
  </div>;
}
