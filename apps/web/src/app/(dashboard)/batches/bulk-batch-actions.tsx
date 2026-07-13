"use client";

import { Loader2, RefreshCw } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { apiJson, getApiErrorMessage } from "@/lib/api";

const ASR_PROVIDER_OPTIONS = [
  { value: "tencent", label: "Tencent ASR", model: "16k_zh_en" },
  { value: "qwen", label: "Qwen ASR", model: "qwen3-asr-flash" },
  { value: "google", label: "Google STT", model: "chirp_2" },
  { value: "gemini", label: "Gemini audio", model: "gemini-3.5-flash" },
] as const;

interface BulkRerunResult {
  queued: number;
  batches: number;
  skipped_active: number;
  skipped_no_audio: number;
}

export function BulkBatchActions() {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [provider, setProvider] = React.useState("tencent");
  const [model, setModel] = React.useState("16k_zh_en");
  const [autoRetry, setAutoRetry] = React.useState(true);
  const [submitting, setSubmitting] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  function onProviderChange(value: string) {
    setProvider(value);
    setModel(ASR_PROVIDER_OPTIONS.find((option) => option.value === value)?.model ?? "");
  }

  async function onSubmit() {
    setSubmitting(true);
    setNotice(null);
    setError(null);
    try {
      const trimmedModel = model.trim();
      const result = await apiJson<BulkRerunResult>("/api/batches/bulk-rerun-stt", "post", {
        body: {
          asr_provider: provider,
          asr_model: trimmedModel.length > 0 ? trimmedModel : null,
          auto_retry_limit: autoRetry ? 2 : 0,
        },
      });
      const skipped = result.skipped_active + result.skipped_no_audio;
      setNotice(
        `Queued ${result.queued} recordings across ${result.batches} batches` +
          (skipped > 0 ? `; skipped ${skipped}.` : "."),
      );
      setOpen(false);
      router.refresh();
    } catch (caught) {
      setError(getApiErrorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-2">
      <Button variant="outline" onClick={() => setOpen(true)} disabled={submitting}>
        {submitting ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
        )}
        Rerun all
      </Button>
      {notice && (
        <p className="max-w-md text-right text-xs text-emerald-700" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="max-w-md text-right text-xs text-destructive" role="alert">
          {error}
        </p>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rerun all batches</DialogTitle>
            <DialogDescription>
              Re-transcribe completed and failed recordings in every finished batch. Batches that
              are currently processing are skipped.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="bulk-asr-provider">ASR provider</Label>
              <Select
                id="bulk-asr-provider"
                value={provider}
                onChange={(event) => onProviderChange(event.target.value)}
              >
                {ASR_PROVIDER_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="bulk-asr-model">Model</Label>
              <Input
                id="bulk-asr-model"
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="Provider default"
              />
            </div>
            <div className="flex items-center justify-between gap-4 border-t pt-4">
              <div>
                <Label htmlFor="bulk-auto-retry">Automatic retries</Label>
                <p className="text-sm text-muted-foreground">
                  Retry terminal STT or evaluation failures up to two times.
                </p>
              </div>
              <Switch
                id="bulk-auto-retry"
                checked={autoRetry}
                onCheckedChange={setAutoRetry}
              />
            </div>
            <p className="text-sm text-muted-foreground">
              Existing transcripts and evaluations will be replaced by the new run.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button onClick={onSubmit} disabled={submitting}>
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              Queue all recordings
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
