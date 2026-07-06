"use client";

import { Loader2, Plus } from "lucide-react";
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
import { apiCall, getApiErrorMessage } from "@/lib/api";

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

export function NewBatchButton() {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [tradeDate, setTradeDate] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  function show() {
    setName("");
    setTradeDate(today());
    setError(null);
    setOpen(true);
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    if (!tradeDate) {
      setError("Batch date is required.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const batch = await apiCall("/api/batches", "post", {
        body: { name: name.trim(), trade_date: tradeDate },
      });
      setOpen(false);
      router.push(`/batches/${batch.id}`);
    } catch (err) {
      setError(getApiErrorMessage(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <Button onClick={show}>
        <Plus className="mr-2 h-4 w-4" aria-hidden />
        New batch
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New batch</DialogTitle>
            <DialogDescription>
              Create a recording upload batch. The date is used for grouping.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="batch-name">Name</Label>
              <Input
                id="batch-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Friday support calls"
                maxLength={200}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="batch-trade-date">Batch date</Label>
              <Input
                id="batch-trade-date"
                type="date"
                required
                value={tradeDate}
                onChange={(e) => setTradeDate(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Recording timestamps and extensions are read from filenames or ZIP metadata.
              </p>
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={pending || !name.trim() || !tradeDate}>
                {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
                Create batch
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
