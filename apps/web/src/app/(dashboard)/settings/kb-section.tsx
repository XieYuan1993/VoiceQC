"use client";

import { FileText, FlaskConical, Loader2, Pencil, Plus, Trash2, Upload } from "lucide-react";
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
import type { KbDocument, KbDocumentIn } from "@/lib/types";

const STATUS_BADGE: Record<string, BadgeProps["variant"]> = {
  processing: "warning",
  ready: "success",
  failed: "destructive",
};

function DocDialog({
  doc,
  canManage,
  projectId,
  onClose,
  onSaved,
}: {
  doc: KbDocument | null; // null = create
  canManage: boolean;
  projectId?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = doc !== null;
  const readOnly = editing && !canManage;
  const [title, setTitle] = React.useState(doc?.title ?? "");
  const [source, setSource] = React.useState(doc?.source ?? "");
  const [content, setContent] = React.useState("");
  const [loading, setLoading] = React.useState(editing);
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  React.useEffect(() => {
    if (!editing || doc === null) return;
    let active = true;
    void (async () => {
      try {
        const detail = await apiCall("/api/kb/documents/{document_id}", "get", {
          params: { path: { document_id: doc.id }, query: { project_id: projectId || undefined } },
        });
        if (active) {
          setContent(detail.content);
          setLoading(false);
        }
      } catch (e) {
        if (active) {
          setError(getApiErrorMessage(e));
          setLoading(false);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [editing, doc, projectId]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!title.trim()) {
      setError("Title is required.");
      return;
    }
    if (!content.trim()) {
      setError("Content is required.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      if (editing && doc) {
        await apiCall("/api/kb/documents/{document_id}", "patch", {
          params: { path: { document_id: doc.id } },
          body: { title: title.trim(), source: source.trim() || null, content },
        });
      } else {
        const body: KbDocumentIn = {
          title: title.trim(),
          source: source.trim() || null,
          content,
        };
        await apiCall("/api/kb/documents", "post", {
          params: { query: { project_id: projectId || undefined } },
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
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {!editing ? "Add knowledge-base document" : readOnly ? "Document" : "Edit document"}
          </DialogTitle>
          <DialogDescription>
            Policy or product reference text. It is chunked and embedded so the evaluator can check
            whether agents&apos; answers are correct against it. Saving re-indexes the document.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="kb-title">Title</Label>
              <Input
                id="kb-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="VHIS product FAQ"
                readOnly={readOnly}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="kb-source">Source (optional)</Label>
              <Input
                id="kb-source"
                value={source}
                onChange={(e) => setSource(e.target.value)}
                placeholder="policy-v3.pdf / URL"
                readOnly={readOnly}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="kb-content">Content</Label>
            {loading ? (
              <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
              </p>
            ) : (
              <Textarea
                id="kb-content"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={12}
                placeholder="Paste the policy / product reference text here…"
                readOnly={readOnly}
                required
                className="font-mono text-xs"
              />
            )}
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {readOnly ? "Close" : "Cancel"}
            </Button>
            {!readOnly && (
              <Button type="submit" disabled={pending || loading}>
                {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
                {editing ? "Save changes" : "Add document"}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RetrieveDialog({ projectId, onClose }: { projectId?: string; onClose: () => void }) {
  const [query, setQuery] = React.useState("");
  const [hits, setHits] = React.useState<Array<{ seq: number; content: string; score: number }> | null>(
    null,
  );
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function run(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!query.trim()) return;
    setPending(true);
    setError(null);
    setHits(null);
    try {
      const res = await apiCall("/api/kb/documents/retrieve", "post", {
        params: { query: { project_id: projectId || undefined } },
        body: { query: query.trim() },
      });
      setHits(res.hits);
    } catch (err) {
      setError(getApiErrorMessage(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Test retrieval</DialogTitle>
          <DialogDescription>
            Type a customer question to see which knowledge-base passages the evaluator would
            retrieve, and how well they match — a tuning aid for the knowledge base.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={run} className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. can I cancel my policy and get a refund?"
            autoFocus
          />
          <Button type="submit" disabled={pending || !query.trim()}>
            {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
            Search
          </Button>
        </form>
        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
        {hits !== null &&
          (hits.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">
              No chunks retrieved — add a document first.
            </p>
          ) : (
            <ul className="mt-3 max-h-80 space-y-2 overflow-y-auto">
              {hits.map((h, i) => (
                <li key={i} className="rounded-md border bg-muted/40 p-3 text-xs">
                  <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
                    <span>chunk #{h.seq}</span>
                    <span className="tabular-nums">match {Math.round(h.score * 100)}%</span>
                  </div>
                  <p className="whitespace-pre-wrap">{h.content}</p>
                </li>
              ))}
            </ul>
          ))}
      </DialogContent>
    </Dialog>
  );
}

export function KnowledgeBaseSection({
  canManage,
  projectId,
}: {
  canManage: boolean;
  projectId?: string;
}) {
  const [docs, setDocs] = React.useState<KbDocument[] | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [dialog, setDialog] = React.useState<{ open: boolean; doc: KbDocument | null }>({
    open: false,
    doc: null,
  });
  const [retrieveOpen, setRetrieveOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<KbDocument | null>(null);
  const [deletePending, setDeletePending] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const [uploadError, setUploadError] = React.useState<string | null>(null);
  const fileInput = React.useRef<HTMLInputElement>(null);

  const load = React.useCallback(async () => {
    try {
      const list = await apiCall("/api/kb/documents", "get", {
        params: { query: { project_id: projectId || undefined } },
      });
      setDocs(list);
      setLoadError(null);
    } catch (e) {
      setLoadError(getApiErrorMessage(e));
    }
  }, [projectId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const anyProcessing = docs?.some((d) => d.status === "processing") ?? false;
  React.useEffect(() => {
    if (!anyProcessing) return;
    const t = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(t);
  }, [anyProcessing, load]);

  async function onDelete() {
    if (deleting === null) return;
    setDeletePending(true);
    setDeleteError(null);
    try {
      await apiCall("/api/kb/documents/{document_id}", "delete", {
        params: { path: { document_id: deleting.id } },
      });
      setDeleting(null);
      void load();
    } catch (e) {
      setDeleteError(getApiErrorMessage(e));
    } finally {
      setDeletePending(false);
    }
  }

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploadError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const params = new URLSearchParams();
      if (projectId) params.set("project_id", projectId);
      const res = await fetch(`/api/kb/documents/upload?${params.toString()}`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail || `upload failed (${res.status})`);
      }
      void load();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "upload failed");
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle className="text-base">Knowledge base</CardTitle>
            <CardDescription>
              Policy &amp; product reference documents. The evaluator retrieves the most relevant
              passages for each call and judges whether the agent&apos;s answers were correct
              against them (Answer correctness on the recording page).
            </CardDescription>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setRetrieveOpen(true)}>
              <FlaskConical className="mr-2 h-4 w-4" aria-hidden />
              Test retrieval
            </Button>
            {canManage && (
              <>
                <input
                  ref={fileInput}
                  type="file"
                  accept=".pdf,.txt,.md,.markdown,text/plain,application/pdf"
                  className="hidden"
                  onChange={onUpload}
                />
                <Button variant="outline" size="sm" onClick={() => fileInput.current?.click()}>
                  <Upload className="mr-2 h-4 w-4" aria-hidden />
                  Upload file
                </Button>
                <Button size="sm" onClick={() => setDialog({ open: true, doc: null })}>
                  <Plus className="mr-2 h-4 w-4" aria-hidden />
                  Add document
                </Button>
              </>
            )}
          </div>
        </div>
        {uploadError && (
          <p className="mt-2 text-sm text-destructive">Upload failed: {uploadError}</p>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {loadError !== null ? (
          <p className="px-6 pb-6 text-sm text-destructive">Failed to load: {loadError}</p>
        ) : docs === null ? (
          <p className="flex items-center gap-2 px-6 pb-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : docs.length === 0 ? (
          <p className="px-6 pb-6 text-sm text-muted-foreground">
            No documents yet — add or upload policy / product references for answer-correctness
            checks.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Title</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Chunks</TableHead>
                <TableHead className="text-right">Size</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {docs.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="font-medium">
                    <button
                      type="button"
                      className="text-left hover:underline"
                      onClick={() => setDialog({ open: true, doc: d })}
                    >
                      <span className="flex items-center gap-2">
                        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                        {d.title}
                      </span>
                    </button>
                    {d.source && (
                      <span className="ml-6 block text-xs text-muted-foreground">{d.source}</span>
                    )}
                    {d.status === "failed" && d.error && (
                      <span className="ml-6 block text-xs text-destructive">{d.error}</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={STATUS_BADGE[d.status] ?? "neutral"}>
                      {d.status === "processing" && (
                        <Loader2 className="mr-1 h-3 w-3 animate-spin" aria-hidden />
                      )}
                      {d.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{d.chunk_count}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {(d.char_count / 1000).toFixed(1)}k
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        aria-label={`${canManage ? "Edit" : "View"} ${d.title}`}
                        onClick={() => setDialog({ open: true, doc: d })}
                      >
                        <Pencil className="h-4 w-4" aria-hidden />
                      </Button>
                      {canManage && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-destructive hover:text-destructive"
                          aria-label={`Delete ${d.title}`}
                          onClick={() => {
                            setDeleteError(null);
                            setDeleting(d);
                          }}
                        >
                          <Trash2 className="h-4 w-4" aria-hidden />
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      {dialog.open && (
        <DocDialog
          doc={dialog.doc}
          canManage={canManage}
          projectId={projectId}
          onClose={() => setDialog({ open: false, doc: null })}
          onSaved={() => {
            setDialog({ open: false, doc: null });
            void load();
          }}
        />
      )}
      {retrieveOpen && (
        <RetrieveDialog projectId={projectId} onClose={() => setRetrieveOpen(false)} />
      )}

      {deleting !== null && (
        <Dialog open onOpenChange={(o) => !o && setDeleting(null)}>
          <DialogContent className="max-w-sm">
            <DialogHeader>
              <DialogTitle>Delete document</DialogTitle>
              <DialogDescription>
                Delete &quot;{deleting.title}&quot; and its embeddings? Future evaluations stop
                using it; past runs keep their findings.
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
