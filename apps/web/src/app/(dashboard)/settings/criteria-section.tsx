"use client";

import { Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import * as React from "react";

import { Badge, type BadgeProps } from "@/components/ui/badge";
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
import { Select } from "@/components/ui/select";
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
import type { Criterion, CriterionIn } from "@/lib/types";

const KEY_PATTERN = /^[a-z0-9_]{1,64}$/;

const CATEGORY_BADGE: Record<string, BadgeProps["variant"]> = {
  compliance: "info",
  quality: "violet",
};

const SEVERITY_BADGE: Record<string, BadgeProps["variant"]> = {
  info: "info",
  warning: "warning",
  critical: "destructive",
};

const SCORE_TYPE_LABELS: Record<string, string> = {
  pass_fail: "Pass / fail",
  scale_1_5: "Scale 1–5",
};

function CriterionDialog({
  criterion,
  projectId,
  onClose,
  onSaved,
}: {
  criterion: Criterion | null; // null = create
  projectId?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [key, setKey] = React.useState(criterion?.key ?? "");
  const [name, setName] = React.useState(criterion?.name ?? "");
  const [description, setDescription] = React.useState(criterion?.description ?? "");
  const [category, setCategory] = React.useState(criterion?.category ?? "compliance");
  const [scoreType, setScoreType] = React.useState(criterion?.score_type ?? "pass_fail");
  const [severity, setSeverity] = React.useState(criterion?.severity ?? "warning");
  const [weightText, setWeightText] = React.useState(String(criterion?.weight ?? 1));
  const [sortOrderText, setSortOrderText] = React.useState(String(criterion?.sort_order ?? 0));
  const [active, setActive] = React.useState(criterion?.active ?? true);
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const trimmedKey = key.trim();
    if (!KEY_PATTERN.test(trimmedKey)) {
      setError("Key must be 1–64 lowercase letters, digits or underscores.");
      return;
    }
    if (!name.trim() || !description.trim()) {
      setError("Name and rubric are required.");
      return;
    }
    const weight = Number(weightText);
    if (weightText.trim() === "" || !Number.isFinite(weight) || weight < 0 || weight > 10) {
      setError("Weight must be a number between 0 and 10.");
      return;
    }
    const sortOrder = Number(sortOrderText);
    if (sortOrderText.trim() === "" || !Number.isInteger(sortOrder)) {
      setError("Sort order must be an integer.");
      return;
    }
    const body: CriterionIn = {
      key: trimmedKey,
      name: name.trim(),
      description: description.trim(),
      category,
      score_type: scoreType,
      severity,
      weight,
      active,
      sort_order: sortOrder,
    };
    setPending(true);
    setError(null);
    try {
      if (criterion === null) {
        await apiCall("/api/criteria", "post", {
          params: { query: { project_id: projectId || undefined } },
          body,
        });
      } else {
        await apiCall("/api/criteria/{criterion_id}", "patch", {
          params: { path: { criterion_id: criterion.id } },
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
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{criterion === null ? "Add criterion" : "Edit criterion"}</DialogTitle>
          <DialogDescription>
            Edits apply to future evaluations only — past runs keep their criteria snapshot.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="criterion-key">Key</Label>
              <Input
                id="criterion-key"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="risk_disclosure"
                className="font-mono"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="criterion-name">Name</Label>
              <Input
                id="criterion-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Risk disclosure given"
                required
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="criterion-description">
              Rubric — sent verbatim to the evaluator
            </Label>
            <Textarea
              id="criterion-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={5}
              placeholder="What the evaluator should check, and what counts as a pass…"
              required
            />
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="criterion-category">Category</Label>
              <Select
                id="criterion-category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="compliance">compliance</option>
                <option value="quality">quality</option>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="criterion-score-type">Score type</Label>
              <Select
                id="criterion-score-type"
                value={scoreType}
                onChange={(e) => setScoreType(e.target.value)}
              >
                <option value="pass_fail">Pass / fail</option>
                <option value="scale_1_5">Scale 1–5</option>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="criterion-severity">Severity</Label>
              <Select
                id="criterion-severity"
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
              >
                <option value="info">info</option>
                <option value="warning">warning</option>
                <option value="critical">critical</option>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-3 items-end gap-4">
            <div className="space-y-2">
              <Label htmlFor="criterion-weight">Weight (0–10)</Label>
              <Input
                id="criterion-weight"
                type="number"
                step="any"
                min={0}
                max={10}
                value={weightText}
                onChange={(e) => setWeightText(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="criterion-sort-order">Sort order</Label>
              <Input
                id="criterion-sort-order"
                type="number"
                step={1}
                value={sortOrderText}
                onChange={(e) => setSortOrderText(e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2 pb-2">
              <Switch id="criterion-active" checked={active} onCheckedChange={setActive} />
              <Label htmlFor="criterion-active">Active</Label>
            </div>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              {criterion === null ? "Add criterion" : "Save changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function CriteriaSection({
  canManage,
  projectId,
}: {
  canManage: boolean;
  projectId?: string;
}) {
  const [criteria, setCriteria] = React.useState<Criterion[] | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [dialog, setDialog] = React.useState<{ open: boolean; criterion: Criterion | null }>({
    open: false,
    criterion: null,
  });
  const [deleting, setDeleting] = React.useState<Criterion | null>(null);
  const [deletePending, setDeletePending] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setCriteria(null);
    try {
      const list = await apiCall("/api/criteria", "get", {
        params: { query: { include_inactive: true, project_id: projectId || undefined } },
      });
      setCriteria(list);
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
      await apiCall("/api/criteria/{criterion_id}", "delete", {
        params: { path: { criterion_id: deleting.id } },
      });
      setDeleting(null);
      void load();
    } catch (e) {
      setDeleteError(getApiErrorMessage(e));
    } finally {
      setDeletePending(false);
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle className="text-base">Evaluation criteria</CardTitle>
            <CardDescription>
              The rubric every call is scored against. Changes apply to future runs only.
            </CardDescription>
          </div>
          {canManage && (
            <Button
              size="sm"
              className="shrink-0"
              onClick={() => setDialog({ open: true, criterion: null })}
            >
              <Plus className="mr-2 h-4 w-4" aria-hidden />
              Add criterion
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {loadError !== null ? (
          <p className="px-6 pb-6 text-sm text-destructive">
            Failed to load criteria: {loadError}
          </p>
        ) : criteria === null ? (
          <p className="flex items-center gap-2 px-6 pb-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : criteria.length === 0 ? (
          <p className="px-6 pb-6 text-sm text-muted-foreground">
            No criteria yet — add one to start evaluating calls.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-12">Order</TableHead>
                <TableHead>Key</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Score type</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead className="text-right">Weight</TableHead>
                <TableHead>Active</TableHead>
                {canManage && <TableHead className="text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {criteria.map((c) => (
                <TableRow key={c.id} className={c.active ? undefined : "opacity-60"}>
                  <TableCell className="tabular-nums text-muted-foreground">
                    {c.sort_order}
                  </TableCell>
                  <TableCell className="whitespace-nowrap font-mono text-xs">{c.key}</TableCell>
                  <TableCell className="font-medium" title={c.description}>
                    {c.name}
                  </TableCell>
                  <TableCell>
                    <Badge variant={CATEGORY_BADGE[c.category] ?? "neutral"}>{c.category}</Badge>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {SCORE_TYPE_LABELS[c.score_type] ?? c.score_type}
                  </TableCell>
                  <TableCell>
                    <Badge variant={SEVERITY_BADGE[c.severity] ?? "neutral"}>{c.severity}</Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{c.weight}</TableCell>
                  <TableCell>
                    <Badge variant={c.active ? "success" : "neutral"}>
                      {c.active ? "active" : "inactive"}
                    </Badge>
                  </TableCell>
                  {canManage && (
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          aria-label={`Edit ${c.name}`}
                          onClick={() => setDialog({ open: true, criterion: c })}
                        >
                          <Pencil className="h-4 w-4" aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-destructive hover:text-destructive"
                          aria-label={`Delete ${c.name}`}
                          onClick={() => {
                            setDeleteError(null);
                            setDeleting(c);
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
        <CriterionDialog
          criterion={dialog.criterion}
          projectId={projectId}
          onClose={() => setDialog({ open: false, criterion: null })}
          onSaved={() => {
            setDialog({ open: false, criterion: null });
            void load();
          }}
        />
      )}

      {deleting !== null && (
        <Dialog open onOpenChange={(o) => !o && setDeleting(null)}>
          <DialogContent className="max-w-sm">
            <DialogHeader>
              <DialogTitle>Delete criterion</DialogTitle>
              <DialogDescription>
                Delete &quot;{deleting.name}&quot;? Future evaluations stop scoring it; past
                evaluations keep their criteria snapshot and are unaffected. To pause it without
                losing the rubric, deactivate it from Edit instead.
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
