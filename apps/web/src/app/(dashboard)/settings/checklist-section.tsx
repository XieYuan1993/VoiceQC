"use client";

import { ChevronDown, ChevronUp, Info, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { apiCall, getApiErrorMessage } from "@/lib/api";
import type { ChecklistItem, ChecklistItemIn } from "@/lib/types";

const KEY_PATTERN = /^[a-z0-9_]{1,64}$/;

/** Full ChecklistItemIn payload for an existing row with a new sort_order. */
function bodyWithOrder(item: ChecklistItem, sortOrder: number): ChecklistItemIn {
  return {
    key: item.key,
    label: item.label,
    description: item.description,
    required: item.required,
    active: item.active,
    sort_order: sortOrder,
  };
}

function ItemDialog({
  item,
  projectId,
  onClose,
  onSaved,
}: {
  item: ChecklistItem | null; // null = create
  projectId?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [key, setKey] = React.useState(item?.key ?? "");
  const [label, setLabel] = React.useState(item?.label ?? "");
  const [description, setDescription] = React.useState(item?.description ?? "");
  const [required, setRequired] = React.useState(item?.required ?? true);
  const [active, setActive] = React.useState(item?.active ?? true);
  const [sortOrderText, setSortOrderText] = React.useState(String(item?.sort_order ?? 0));
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const trimmedKey = key.trim();
    if (!KEY_PATTERN.test(trimmedKey)) {
      setError("Key must be 1–64 lowercase letters, digits or underscores.");
      return;
    }
    if (!label.trim()) {
      setError("Item is required.");
      return;
    }
    const sortOrder = Number(sortOrderText);
    if (sortOrderText.trim() === "" || !Number.isInteger(sortOrder)) {
      setError("Sort order must be an integer.");
      return;
    }
    const body: ChecklistItemIn = {
      key: trimmedKey,
      label: label.trim(),
      description: description.trim() === "" ? null : description.trim(),
      required,
      active,
      sort_order: sortOrder,
    };
    setPending(true);
    setError(null);
    try {
      if (item === null) {
        await apiCall("/api/checklist-items", "post", {
          params: { query: { project_id: projectId || undefined } },
          body,
        });
      } else {
        await apiCall("/api/checklist-items/{item_id}", "patch", {
          params: { path: { item_id: item.id } },
          body,
        });
      }
      onSaved();
    } catch (err) {
      setError(getApiErrorMessage(err));
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {item === null ? "Add checklist item" : "Edit checklist item"}
          </DialogTitle>
          <DialogDescription>
            A required item the agent must cover. The evaluator semantic-matches whether it was
            addressed — exact wording is not needed.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="ck-key">Key</Label>
              <Input
                id="ck-key"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="verify_identity"
                className="font-mono"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ck-sort-order">Sort order</Label>
              <Input
                id="ck-sort-order"
                type="number"
                step={1}
                value={sortOrderText}
                onChange={(e) => setSortOrderText(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="ck-label">Item / question</Label>
            <Input
              id="ck-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Verify the customer's identity (policy no. or HKID)"
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="ck-description">What counts as covered (optional)</Label>
            <Textarea
              id="ck-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="e.g. the agent asks for and confirms the policy number or HKID"
            />
          </div>
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <Switch id="ck-required" checked={required} onCheckedChange={setRequired} />
              <Label htmlFor="ck-required">Required</Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch id="ck-active" checked={active} onCheckedChange={setActive} />
              <Label htmlFor="ck-active">Active</Label>
            </div>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              {item === null ? "Add item" : "Save changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ChecklistSection({
  canManage,
  projectId,
}: {
  canManage: boolean;
  projectId?: string;
}) {
  const [items, setItems] = React.useState<ChecklistItem[] | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [dialog, setDialog] = React.useState<{ open: boolean; item: ChecklistItem | null }>({
    open: false,
    item: null,
  });
  const [deleting, setDeleting] = React.useState<ChecklistItem | null>(null);
  const [deletePending, setDeletePending] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const [reordering, setReordering] = React.useState(false);

  const load = React.useCallback(async () => {
    setItems(null);
    try {
      const list = await apiCall("/api/checklist-items", "get", {
        params: { query: { include_inactive: true, project_id: projectId || undefined } },
      });
      setItems(list);
      setLoadError(null);
    } catch (e) {
      setLoadError(getApiErrorMessage(e));
    }
  }, [projectId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function onDelete() {
    if (deleting === null) return;
    setDeletePending(true);
    setDeleteError(null);
    try {
      await apiCall("/api/checklist-items/{item_id}", "delete", {
        params: { path: { item_id: deleting.id } },
      });
      setDeleting(null);
      void load();
    } catch (e) {
      setDeleteError(getApiErrorMessage(e));
    } finally {
      setDeletePending(false);
    }
  }

  async function move(item: ChecklistItem, dir: -1 | 1) {
    if (items === null) return;
    const idx = items.findIndex((x) => x.id === item.id);
    const j = idx + dir;
    if (idx < 0 || j < 0 || j >= items.length) return;
    const other = items[j];
    // Swap the pair's sort_order; if they tie, fall back to list positions.
    let orderForItem = other.sort_order;
    let orderForOther = item.sort_order;
    if (orderForItem === orderForOther) {
      orderForItem = j;
      orderForOther = idx;
    }
    setReordering(true);
    setLoadError(null);
    try {
      await apiCall("/api/checklist-items/{item_id}", "patch", {
        params: { path: { item_id: item.id } },
        body: bodyWithOrder(item, orderForItem),
      });
      await apiCall("/api/checklist-items/{item_id}", "patch", {
        params: { path: { item_id: other.id } },
        body: bodyWithOrder(other, orderForOther),
      });
      await load();
    } catch (e) {
      setLoadError(getApiErrorMessage(e));
    } finally {
      setReordering(false);
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle className="text-base">Checklist</CardTitle>
            <CardDescription>
              Required items the agent must cover on each call. The evaluator checks coverage by
              meaning, and the recording page reports what was missed.
            </CardDescription>
            <p className="mt-2 flex max-w-prose items-start gap-1.5 text-xs text-muted-foreground">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              <span>
                Checklist items track{" "}
                <span className="font-medium text-foreground">coverage</span> only (the call&apos;s
                script-adherence %). For weighted pass/fail scoring that drives the call score and
                risk flags, use <span className="font-medium text-foreground">Criteria</span>{" "}
                instead.
              </span>
            </p>
          </div>
          {canManage && (
            <Button
              size="sm"
              className="shrink-0"
              onClick={() => setDialog({ open: true, item: null })}
            >
              <Plus className="mr-2 h-4 w-4" aria-hidden />
              Add item
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {loadError !== null ? (
          <p className="px-6 pb-6 text-sm text-destructive">
            Failed to load checklist: {loadError}
          </p>
        ) : items === null ? (
          <p className="flex items-center gap-2 px-6 pb-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : items.length === 0 ? (
          <p className="px-6 pb-6 text-sm text-muted-foreground">
            No checklist items yet — add the questions or steps agents must cover.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Key</TableHead>
                <TableHead>Item / question</TableHead>
                <TableHead>Required</TableHead>
                <TableHead>Active</TableHead>
                {canManage && <TableHead className="text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((it, idx) => (
                <TableRow key={it.id} className={it.active ? undefined : "opacity-60"}>
                  <TableCell className="whitespace-nowrap font-mono text-xs">{it.key}</TableCell>
                  <TableCell className="font-medium" title={it.description ?? undefined}>
                    {it.label}
                  </TableCell>
                  <TableCell>
                    <Badge variant={it.required ? "info" : "neutral"}>
                      {it.required ? "required" : "optional"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={it.active ? "success" : "neutral"}>
                      {it.active ? "active" : "inactive"}
                    </Badge>
                  </TableCell>
                  {canManage && (
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground"
                          aria-label={`Move ${it.label} up`}
                          disabled={idx === 0 || reordering}
                          onClick={() => void move(it, -1)}
                        >
                          <ChevronUp className="h-4 w-4" aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground"
                          aria-label={`Move ${it.label} down`}
                          disabled={idx === items.length - 1 || reordering}
                          onClick={() => void move(it, 1)}
                        >
                          <ChevronDown className="h-4 w-4" aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          aria-label={`Edit ${it.label}`}
                          onClick={() => setDialog({ open: true, item: it })}
                        >
                          <Pencil className="h-4 w-4" aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-destructive hover:text-destructive"
                          aria-label={`Delete ${it.label}`}
                          onClick={() => {
                            setDeleteError(null);
                            setDeleting(it);
                          }}
                        >
                          <Trash2 className="h-4 w-4" aria-hidden />
                        </Button>
                      </div>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      {dialog.open && (
        <ItemDialog
          item={dialog.item}
          projectId={projectId}
          onClose={() => setDialog({ open: false, item: null })}
          onSaved={() => {
            setDialog({ open: false, item: null });
            void load();
          }}
        />
      )}

      {deleting !== null && (
        <Dialog open onOpenChange={(o) => !o && setDeleting(null)}>
          <DialogContent className="max-w-sm">
            <DialogHeader>
              <DialogTitle>Delete checklist item</DialogTitle>
              <DialogDescription>
                Delete &quot;{deleting.label}&quot;? Future evaluations stop checking it; past runs
                are kept.
              </DialogDescription>
            </DialogHeader>
            {deleteError && <p className="text-sm text-destructive">{deleteError}</p>}
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleting(null)}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={onDelete} disabled={deletePending}>
                {deletePending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
                Delete
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </Card>
  );
}
