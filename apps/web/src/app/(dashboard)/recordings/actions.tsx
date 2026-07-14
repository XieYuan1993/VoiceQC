"use client";

import { Download, Loader2, RefreshCw } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiCall, getApiErrorMessage } from "@/lib/api";

export function RecordingActions({
  projectId,
  status,
  q,
  canManage,
}: {
  projectId: string;
  status: string;
  q: string;
  canManage: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const [pending, setPending] = React.useState(false);
  const [result, setResult] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (status) params.set("status", status);
  if (q) params.set("q", q);
  const exportHref = `/api/recordings/export?${params.toString()}`;

  async function reevaluate() {
    setPending(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiCall("/api/recordings/reevaluate", "post", {
        params: { query: { project_id: projectId || undefined } },
      });
      setResult(`Queued ${res.queued} call${res.queued === 1 ? "" : "s"} for re-evaluation.`);
    } catch (e) {
      setError(getApiErrorMessage(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button asChild variant="outline" size="sm">
        <a href={exportHref} download>
          <Download className="mr-2 h-4 w-4" aria-hidden />
          Export CSV
        </a>
      </Button>
      {canManage && (
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setResult(null);
            setError(null);
            setOpen(true);
          }}
        >
          <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
          Re-evaluate all
        </Button>
      )}
      {open && (
        <Dialog open onOpenChange={(o) => !o && setOpen(false)}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>Re-evaluate all transcribed calls?</DialogTitle>
              <DialogDescription>
                Re-runs the LLM evaluation for every transcribed recording in this
                project under the current criteria, checklist and knowledge base. This consumes LLM
                tokens; previous runs are kept.
              </DialogDescription>
            </DialogHeader>
            {error && <p className="text-sm text-destructive">{error}</p>}
            {result && <p className="text-sm text-emerald-600 dark:text-emerald-400">{result}</p>}
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>
                {result ? "Close" : "Cancel"}
              </Button>
              {!result && (
                <Button onClick={reevaluate} disabled={pending}>
                  {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
                  Re-evaluate all
                </Button>
              )}
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
