"use client";

import { Loader2, Pencil, Plus, Trash2, Upload } from "lucide-react";
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
import { apiCall, getApiErrorMessage, uploadMultipart } from "@/lib/api";
import type { Term, TermImportResult, TermIn } from "@/lib/types";

const MAX_ALIAS_CHIPS = 4;

function TermDialog({
  term,
  projectId,
  onClose,
  onSaved,
}: {
  term: Term | null; // null = create
  projectId?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [category, setCategory] = React.useState(term?.category ?? "");
  const [canonical, setCanonical] = React.useState(term?.canonical ?? "");
  const [stockCode, setStockCode] = React.useState(term?.stock_code ?? "");
  const [aliasesText, setAliasesText] = React.useState((term?.aliases ?? []).join(", "));
  const [boostText, setBoostText] = React.useState(term?.boost != null ? String(term.boost) : "");
  const [active, setActive] = React.useState(term?.active ?? true);
  const [notes, setNotes] = React.useState(term?.notes ?? "");
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const boost = boostText.trim() === "" ? null : Number(boostText);
    if (!category.trim() || !canonical.trim()) {
      setError("Category and canonical name are required.");
      return;
    }
    if (boost !== null && !Number.isFinite(boost)) {
      setError("Boost must be a number.");
      return;
    }
    const body: TermIn = {
      category: category.trim(),
      canonical: canonical.trim(),
      stock_code: stockCode.trim() === "" ? null : stockCode.trim(),
      aliases: aliasesText
        .split(",")
        .map((a) => a.trim())
        .filter(Boolean),
      boost,
      active,
      notes: notes.trim() === "" ? null : notes.trim(),
    };
    setPending(true);
    setError(null);
    try {
      if (term === null) {
        await apiCall("/api/terms", "post", {
          params: { query: { project_id: projectId || undefined } },
          body,
        });
      } else {
        await apiCall("/api/terms/{term_id}", "patch", {
          params: { path: { term_id: term.id } },
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
          <DialogTitle>{term === null ? "Add term" : "Edit term"}</DialogTitle>
          <DialogDescription>
            Terms feed speech adaptation — canonical name plus spoken aliases.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="term-category">Category</Label>
              <Input
                id="term-category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="product, person, jargon…"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="term-stock-code">Code (optional)</Label>
              <Input
                id="term-stock-code"
                value={stockCode}
                onChange={(e) => setStockCode(e.target.value)}
                placeholder="optional identifier"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="term-canonical">Canonical name</Label>
            <Input
              id="term-canonical"
              value={canonical}
              onChange={(e) => setCanonical(e.target.value)}
              placeholder="e.g. Tencent"
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="term-aliases">Aliases (comma-separated)</Label>
            <Input
              id="term-aliases"
              value={aliasesText}
              onChange={(e) => setAliasesText(e.target.value)}
              placeholder="騰訊, 企鵝, Tencent Holdings"
            />
          </div>
          <div className="grid grid-cols-2 items-end gap-4">
            <div className="space-y-2">
              <Label htmlFor="term-boost">Boost (optional)</Label>
              <Input
                id="term-boost"
                type="number"
                step="any"
                value={boostText}
                onChange={(e) => setBoostText(e.target.value)}
                placeholder="STT adaptation boost"
              />
            </div>
            <div className="flex items-center gap-2 pb-2">
              <Switch id="term-active" checked={active} onCheckedChange={setActive} />
              <Label htmlFor="term-active">Active</Label>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="term-notes">Notes (optional)</Label>
            <Textarea
              id="term-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              {term === null ? "Add term" : "Save changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function TermsSection({
  canManage,
  projectId,
}: {
  canManage: boolean;
  projectId?: string;
}) {
  const [terms, setTerms] = React.useState<Term[] | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [category, setCategory] = React.useState("");
  const [dialog, setDialog] = React.useState<{ open: boolean; term: Term | null }>({
    open: false,
    term: null,
  });
  const [deleting, setDeleting] = React.useState<Term | null>(null);
  const [deletePending, setDeletePending] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const [importing, setImporting] = React.useState(false);
  const [importMessage, setImportMessage] = React.useState<string | null>(null);
  const [importError, setImportError] = React.useState<string | null>(null);
  const csvInputRef = React.useRef<HTMLInputElement>(null);

  const load = React.useCallback(async () => {
    setTerms(null);
    try {
      const list = await apiCall("/api/terms", "get", {
        params: { query: { include_inactive: true, project_id: projectId || undefined } },
      });
      setTerms(list);
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
      await apiCall("/api/terms/{term_id}", "delete", {
        params: { path: { term_id: deleting.id } },
      });
      setDeleting(null);
      void load();
    } catch (e) {
      setDeleteError(getApiErrorMessage(e));
    } finally {
      setDeletePending(false);
    }
  }

  async function onCsvPicked(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (!file) return;
    setImporting(true);
    setImportMessage(null);
    setImportError(null);
    try {
      const importPath = projectId
        ? `/api/terms/import-csv?project_id=${encodeURIComponent(projectId)}`
        : "/api/terms/import-csv";
      const res = await uploadMultipart<TermImportResult>(importPath, file);
      setImportMessage(`Imported: ${res.created} created, ${res.updated} updated.`);
      void load();
    } catch (err) {
      setImportError(getApiErrorMessage(err));
    } finally {
      setImporting(false);
    }
  }

  const categories =
    terms === null ? [] : Array.from(new Set(terms.map((t) => t.category))).sort();
  const filtered =
    terms === null ? [] : category ? terms.filter((t) => t.category === category) : terms;

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle className="text-base">Industry terms</CardTitle>
            <CardDescription>
              Glossary that improves transcription accuracy — names, jargon, and their aliases.
            </CardDescription>
          </div>
          {canManage && (
            <div className="flex shrink-0 items-center gap-2">
              <input
                ref={csvInputRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={onCsvPicked}
              />
              <Button
                variant="outline"
                size="sm"
                disabled={importing}
                onClick={() => csvInputRef.current?.click()}
              >
                {importing ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Upload className="mr-2 h-4 w-4" aria-hidden />
                )}
                Import CSV
              </Button>
              <Button size="sm" onClick={() => setDialog({ open: true, term: null })}>
                <Plus className="mr-2 h-4 w-4" aria-hidden />
                Add term
              </Button>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <Select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            wrapperClassName="w-52"
            aria-label="Filter terms by category"
          >
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
          {importMessage && (
            <span className="text-sm text-emerald-700 dark:text-emerald-400">{importMessage}</span>
          )}
          {importError && <span className="text-sm text-destructive">{importError}</span>}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {loadError !== null ? (
          <p className="px-6 pb-6 text-sm text-destructive">Failed to load terms: {loadError}</p>
        ) : terms === null ? (
          <p className="flex items-center gap-2 px-6 pb-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : filtered.length === 0 ? (
          <p className="px-6 pb-6 text-sm text-muted-foreground">
            {terms.length === 0
              ? "No terms yet — add one or import the CSV."
              : "No terms in this category."}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Category</TableHead>
                <TableHead>Canonical</TableHead>
                <TableHead>Code</TableHead>
                <TableHead>Aliases</TableHead>
                <TableHead>Active</TableHead>
                {canManage && <TableHead className="text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((t) => {
                const aliases = t.aliases ?? [];
                return (
                  <TableRow key={t.id} className={t.active ? undefined : "opacity-60"}>
                    <TableCell className="whitespace-nowrap">{t.category}</TableCell>
                    <TableCell className="font-medium">{t.canonical}</TableCell>
                    <TableCell className="tabular-nums">{t.stock_code ?? "—"}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {aliases.length === 0 && (
                          <span className="text-muted-foreground">—</span>
                        )}
                        {aliases.slice(0, MAX_ALIAS_CHIPS).map((a) => (
                          <Badge key={a} variant="secondary" className="font-normal">
                            {a}
                          </Badge>
                        ))}
                        {aliases.length > MAX_ALIAS_CHIPS && (
                          <Badge
                            variant="outline"
                            className="font-normal text-muted-foreground"
                            title={aliases.slice(MAX_ALIAS_CHIPS).join(", ")}
                          >
                            +{aliases.length - MAX_ALIAS_CHIPS} more
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={t.active ? "success" : "neutral"}>
                        {t.active ? "active" : "inactive"}
                      </Badge>
                    </TableCell>
                    {canManage && (
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            aria-label={`Edit ${t.canonical}`}
                            onClick={() => setDialog({ open: true, term: t })}
                          >
                            <Pencil className="h-4 w-4" aria-hidden />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-destructive hover:text-destructive"
                            aria-label={`Delete ${t.canonical}`}
                            onClick={() => {
                              setDeleteError(null);
                              setDeleting(t);
                            }}
                          >
                            <Trash2 className="h-4 w-4" aria-hidden />
                          </Button>
                        </div>
                      </TableCell>
                    )}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>

      {dialog.open && (
        <TermDialog
          term={dialog.term}
          projectId={projectId}
          onClose={() => setDialog({ open: false, term: null })}
          onSaved={() => {
            setDialog({ open: false, term: null });
            void load();
          }}
        />
      )}

      {deleting !== null && (
        <Dialog open onOpenChange={(o) => !o && setDeleting(null)}>
          <DialogContent className="max-w-sm">
            <DialogHeader>
              <DialogTitle>Delete term</DialogTitle>
              <DialogDescription>
                Delete &quot;{deleting.canonical}&quot;? This cannot be undone. To stop using a
                term without losing it, deactivate it from Edit instead.
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
