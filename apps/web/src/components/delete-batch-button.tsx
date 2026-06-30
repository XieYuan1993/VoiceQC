"use client";

import { AlertTriangle, Loader2, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
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

/** Delete a batch (and, by cascade, its recordings + audio) behind a confirm
 * dialog. `icon` for table rows, `button` for the detail header. */
export function DeleteBatchButton({
  batchId,
  batchName,
  fileCount,
  variant = "icon",
  redirectTo,
}: {
  batchId: string;
  batchName: string;
  fileCount: number;
  variant?: "icon" | "button";
  redirectTo?: string;
}) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function onConfirm() {
    setDeleting(true);
    setError(null);
    try {
      await apiCall("/api/batches/{batch_id}", "delete", {
        params: { path: { batch_id: batchId } },
      });
      setOpen(false);
      if (redirectTo) router.push(redirectTo as never);
      else router.refresh();
    } catch (e) {
      setError(getApiErrorMessage(e));
      setDeleting(false);
    }
  }

  return (
    <>
      {variant === "icon" ? (
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 text-muted-foreground hover:text-destructive"
          aria-label={`Delete batch ${batchName}`}
          onClick={() => setOpen(true)}
        >
          <Trash2 className="h-4 w-4" aria-hidden />
        </Button>
      ) : (
        <Button
          variant="outline"
          size="sm"
          className="text-destructive hover:text-destructive"
          onClick={() => setOpen(true)}
        >
          <Trash2 className="mr-2 h-4 w-4" aria-hidden />
          Delete batch
        </Button>
      )}
      <Dialog open={open} onOpenChange={(o) => !deleting && setOpen(o)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" aria-hidden />
              Delete batch?
            </DialogTitle>
            <DialogDescription>
              This permanently deletes{" "}
              <span className="font-medium text-foreground">{batchName}</span>
              {fileCount > 0 ? (
                <>
                  {" "}
                  and its {fileCount} recording{fileCount === 1 ? "" : "s"} — transcripts,
                  evaluations and audio included
                </>
              ) : null}
              . This can&apos;t be undone.
            </DialogDescription>
          </DialogHeader>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={deleting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={() => void onConfirm()} disabled={deleting}>
              {deleting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Trash2 className="mr-2 h-4 w-4" aria-hidden />
              )}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
