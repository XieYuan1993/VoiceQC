"use client";

import { Loader2, Lock, Pencil, Plus, Trash2 } from "lucide-react";
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
import type { ExtractionField, ExtractionFieldIn } from "@/lib/types";

const KEY_PATTERN = /^[a-z0-9_]{1,64}$/;

const FIELD_TYPES = ["string", "number", "boolean", "date", "enum"] as const;

function FieldDialog({
  field,
  projectId,
  onClose,
  onSaved,
}: {
  field: ExtractionField | null; // null = create (always call scope)
  projectId?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [key, setKey] = React.useState(field?.key ?? "");
  const [label, setLabel] = React.useState(field?.label ?? "");
  const [description, setDescription] = React.useState(field?.description ?? "");
  const [fieldType, setFieldType] = React.useState(field?.field_type ?? "string");
  const [enumOptionsText, setEnumOptionsText] = React.useState(
    (field?.enum_options ?? []).join(", "),
  );
  const [sortOrderText, setSortOrderText] = React.useState(String(field?.sort_order ?? 0));
  const [active, setActive] = React.useState(field?.active ?? true);
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
      setError("Label is required.");
      return;
    }
    const enumOptions = enumOptionsText
      .split(",")
      .map((o) => o.trim())
      .filter(Boolean);
    if (fieldType === "enum" && enumOptions.length === 0) {
      setError("Enum fields need at least one option.");
      return;
    }
    const sortOrder = Number(sortOrderText);
    if (sortOrderText.trim() === "" || !Number.isInteger(sortOrder)) {
      setError("Sort order must be an integer.");
      return;
    }
    const body: ExtractionFieldIn = {
      key: trimmedKey,
      label: label.trim(),
      description: description.trim() === "" ? null : description.trim(),
      field_type: fieldType,
      enum_options: fieldType === "enum" ? enumOptions : null,
      scope: field?.scope ?? "call", // trade-scope fields are system-defined
      active,
      sort_order: sortOrder,
    };
    setPending(true);
    setError(null);
    try {
      if (field === null) {
        await apiCall("/api/extraction-fields", "post", {
          params: { query: { project_id: projectId || undefined } },
          body,
        });
      } else {
        await apiCall("/api/extraction-fields/{field_id}", "patch", {
          params: { path: { field_id: field.id } },
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
          <DialogTitle>{field === null ? "Add call field" : "Edit call field"}</DialogTitle>
          <DialogDescription>
            Call-level value the evaluator extracts from every recording. Trade fields are
            system-defined and locked.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="field-key">Key</Label>
              <Input
                id="field-key"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="callback_promised"
                className="font-mono"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="field-label">Label</Label>
              <Input
                id="field-label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Callback promised"
                required
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="field-description">Description (optional)</Label>
            <Textarea
              id="field-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Hint for the extractor — what to look for and how to format it"
            />
          </div>
          <div className="grid grid-cols-2 items-end gap-4">
            <div className="space-y-2">
              <Label htmlFor="field-type">Type</Label>
              <Select
                id="field-type"
                value={fieldType}
                onChange={(e) => setFieldType(e.target.value)}
              >
                {FIELD_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="field-sort-order">Sort order</Label>
              <Input
                id="field-sort-order"
                type="number"
                step={1}
                value={sortOrderText}
                onChange={(e) => setSortOrderText(e.target.value)}
              />
            </div>
          </div>
          {fieldType === "enum" && (
            <div className="space-y-2">
              <Label htmlFor="field-enum-options">Options (comma-separated)</Label>
              <Input
                id="field-enum-options"
                value={enumOptionsText}
                onChange={(e) => setEnumOptionsText(e.target.value)}
                placeholder="yes, no, unclear"
              />
            </div>
          )}
          <div className="flex items-center gap-2">
            <Switch id="field-active" checked={active} onCheckedChange={setActive} />
            <Label htmlFor="field-active">Active</Label>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              {field === null ? "Add field" : "Save changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function FieldsTable({
  fields,
  canManage,
  onEdit,
  onDelete,
}: {
  fields: ExtractionField[];
  canManage: boolean;
  onEdit: (f: ExtractionField) => void;
  onDelete: (f: ExtractionField) => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Key</TableHead>
          <TableHead>Label</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Active</TableHead>
          {canManage && <TableHead className="text-right">Actions</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {fields.map((f) => (
          <TableRow key={f.id} className={f.active ? undefined : "opacity-60"}>
            <TableCell className="whitespace-nowrap font-mono text-xs">
              <span className="inline-flex items-center gap-1.5">
                {f.is_system && (
                  <Lock
                    className="h-3 w-3 text-muted-foreground"
                    aria-label="System field — locked"
                  />
                )}
                {f.key}
              </span>
            </TableCell>
            <TableCell className="font-medium" title={f.description ?? undefined}>
              {f.label}
            </TableCell>
            <TableCell>
              {f.field_type}
              {f.field_type === "enum" && f.enum_options && f.enum_options.length > 0 && (
                <span
                  className="block max-w-[260px] truncate text-xs text-muted-foreground"
                  title={f.enum_options.join(", ")}
                >
                  {f.enum_options.join(", ")}
                </span>
              )}
            </TableCell>
            <TableCell>
              <Badge variant={f.active ? "success" : "neutral"}>
                {f.active ? "active" : "inactive"}
              </Badge>
            </TableCell>
            {canManage && (
              <TableCell className="text-right">
                {f.is_system ? (
                  <span
                    className="inline-flex items-center gap-1 text-xs text-muted-foreground"
                    title="System field — reconciliation depends on its shape"
                  >
                    <Lock className="h-3 w-3" aria-hidden />
                    locked
                  </span>
                ) : (
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      aria-label={`Edit ${f.label}`}
                      onClick={() => onEdit(f)}
                    >
                      <Pencil className="h-4 w-4" aria-hidden />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-destructive hover:text-destructive"
                      aria-label={`Delete ${f.label}`}
                      onClick={() => onDelete(f)}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </Button>
                  </div>
                )}
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function ExtractionFieldsSection({
  canManage,
  projectId,
}: {
  canManage: boolean;
  projectId?: string;
}) {
  const [fields, setFields] = React.useState<ExtractionField[] | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [dialog, setDialog] = React.useState<{ open: boolean; field: ExtractionField | null }>({
    open: false,
    field: null,
  });
  const [deleting, setDeleting] = React.useState<ExtractionField | null>(null);
  const [deletePending, setDeletePending] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setFields(null);
    try {
      const list = await apiCall("/api/extraction-fields", "get", {
        params: { query: { include_inactive: true, project_id: projectId || undefined } },
      });
      setFields(list);
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
      await apiCall("/api/extraction-fields/{field_id}", "delete", {
        params: { path: { field_id: deleting.id } },
      });
      setDeleting(null);
      void load();
    } catch (e) {
      setDeleteError(getApiErrorMessage(e));
    } finally {
      setDeletePending(false);
    }
  }

  const tradeFields = fields === null ? [] : fields.filter((f) => f.scope === "trade");
  const callFields = fields === null ? [] : fields.filter((f) => f.scope !== "trade");

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle className="text-base">Extraction fields</CardTitle>
            <CardDescription>
              Structured values the evaluator pulls out of each call. Trade fields are
              system-defined; call fields are configurable.
            </CardDescription>
          </div>
          {canManage && (
            <Button
              size="sm"
              className="shrink-0"
              onClick={() => setDialog({ open: true, field: null })}
            >
              <Plus className="mr-2 h-4 w-4" aria-hidden />
              Add call field
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {loadError !== null ? (
          <p className="px-6 pb-6 text-sm text-destructive">Failed to load fields: {loadError}</p>
        ) : fields === null ? (
          <p className="flex items-center gap-2 px-6 pb-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : fields.length === 0 ? (
          <p className="px-6 pb-6 text-sm text-muted-foreground">No extraction fields found.</p>
        ) : (
          <div className="space-y-4 pb-2">
            <div>
              <h3 className="flex items-center gap-1.5 px-6 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <Lock className="h-3 w-3" aria-hidden />
                Trade fields (per instruction)
              </h3>
              {tradeFields.length === 0 ? (
                <p className="px-6 py-2 text-sm text-muted-foreground">No trade fields.</p>
              ) : (
                <FieldsTable
                  fields={tradeFields}
                  canManage={canManage}
                  onEdit={(f) => setDialog({ open: true, field: f })}
                  onDelete={(f) => {
                    setDeleteError(null);
                    setDeleting(f);
                  }}
                />
              )}
            </div>
            <div>
              <h3 className="px-6 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Call fields (per recording)
              </h3>
              {callFields.length === 0 ? (
                <p className="px-6 py-2 text-sm text-muted-foreground">
                  No call fields yet — add one to extract extra context from each call.
                </p>
              ) : (
                <FieldsTable
                  fields={callFields}
                  canManage={canManage}
                  onEdit={(f) => setDialog({ open: true, field: f })}
                  onDelete={(f) => {
                    setDeleteError(null);
                    setDeleting(f);
                  }}
                />
              )}
            </div>
          </div>
        )}
      </CardContent>

      {dialog.open && (
        <FieldDialog
          field={dialog.field}
          projectId={projectId}
          onClose={() => setDialog({ open: false, field: null })}
          onSaved={() => {
            setDialog({ open: false, field: null });
            void load();
          }}
        />
      )}

      {deleting !== null && (
        <Dialog open onOpenChange={(o) => !o && setDeleting(null)}>
          <DialogContent className="max-w-sm">
            <DialogHeader>
              <DialogTitle>Delete field</DialogTitle>
              <DialogDescription>
                Delete &quot;{deleting.label}&quot;? Future evaluations stop extracting it; values
                already extracted on past runs are kept.
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
