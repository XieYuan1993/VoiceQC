"use client";

import { DownloadCloud, FlaskConical, Loader2, Lock, Pencil, Plus } from "lucide-react";
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
import { formatDateTime, todayISO } from "@/lib/format";
import type { TxnSource, TxnSourceIn, TxnSourceTest } from "@/lib/types";

// Keys the API requires per kind (mirrors _validate_source in the backend).
const CONFIG_HINT: Record<string, string> = {
  csv: 'Must include "column_mapping" (canonical field → file column).',
  api: 'Must include "base_url", "path_template" and "field_mapping".',
};

const SAMPLE_KEYS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "ext_txn_id", label: "Ext ref" },
  { key: "stock_code", label: "Stock" },
  { key: "side", label: "Side" },
  { key: "quantity", label: "Qty" },
  { key: "price", label: "Price" },
  { key: "channel", label: "Channel" },
];

function sampleText(v: unknown): string {
  if (v == null || v === "") return "—";
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

function SourceDialog({
  source,
  onClose,
  onSaved,
}: {
  source: TxnSource | null; // null = create
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = React.useState(source?.name ?? "");
  const [kind, setKind] = React.useState(source?.kind ?? "csv");
  const [active, setActive] = React.useState(source?.active ?? true);
  const [scheduleCron, setScheduleCron] = React.useState(source?.schedule_cron ?? "");
  const [credential, setCredential] = React.useState("");
  const [configText, setConfigText] = React.useState(
    JSON.stringify(source?.config ?? {}, null, 2),
  );
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    let config: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(configText);
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("not an object");
      }
      config = parsed as Record<string, unknown>;
    } catch {
      setError("Config must be a JSON object.");
      return;
    }
    const body: TxnSourceIn = {
      name: name.trim(),
      kind,
      active,
      config,
      // Empty string keeps the stored secret (backend ignores falsy values).
      credential: credential || null,
      schedule_cron: scheduleCron.trim() || null,
    };
    setPending(true);
    setError(null);
    try {
      if (source === null) {
        await apiCall("/api/txn-sources", "post", { body });
      } else {
        await apiCall("/api/txn-sources/{source_id}", "patch", {
          params: { path: { source_id: source.id } },
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
          <DialogTitle>{source === null ? "New source" : "Edit source"}</DialogTitle>
          <DialogDescription>
            CSV sources are mapping templates for uploaded files; API sources are pulled on
            demand or on a schedule.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="source-name">Name</Label>
              <Input
                id="source-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Back-office EOD CSV"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="source-kind">Kind</Label>
              <Select id="source-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="csv">csv</option>
                <option value="api">api</option>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 items-end gap-4">
            <div className="space-y-2">
              <Label htmlFor="source-cron">Schedule (cron, optional)</Label>
              <Input
                id="source-cron"
                value={scheduleCron}
                onChange={(e) => setScheduleCron(e.target.value)}
                placeholder="0 18 * * 1-5"
                className="font-mono"
              />
            </div>
            <div className="flex items-center gap-2 pb-2">
              <Switch id="source-active" checked={active} onCheckedChange={setActive} />
              <Label htmlFor="source-active">Active</Label>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="source-credential">Credential</Label>
            <Input
              id="source-credential"
              type="password"
              value={credential}
              onChange={(e) => setCredential(e.target.value)}
              placeholder={
                source?.has_credential
                  ? "Leave blank to keep the current secret"
                  : "API key / token (optional)"
              }
              autoComplete="new-password"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="source-config">Config (JSON)</Label>
            <Textarea
              id="source-config"
              value={configText}
              onChange={(e) => setConfigText(e.target.value)}
              rows={8}
              className="font-mono text-xs"
              spellCheck={false}
            />
            <p className="text-xs text-muted-foreground">{CONFIG_HINT[kind]}</p>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              {source === null ? "Create source" : "Save changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function PullDialog({
  source,
  onClose,
  onStarted,
}: {
  source: TxnSource;
  onClose: () => void;
  onStarted: () => void;
}) {
  const [tradeDate, setTradeDate] = React.useState(todayISO());
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      await apiCall("/api/txn-sources/{source_id}/pull", "post", {
        params: { path: { source_id: source.id }, query: { trade_date: tradeDate } },
      });
      onStarted();
    } catch (err) {
      setError(getApiErrorMessage(err));
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Pull from {source.name}</DialogTitle>
          <DialogDescription>
            Queues an API pull for one trade date — progress shows in Imports.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="pull-trade-date">Trade date</Label>
            <Input
              id="pull-trade-date"
              type="date"
              required
              value={tradeDate}
              onChange={(e) => setTradeDate(e.target.value)}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending || !tradeDate}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              Pull now
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

interface TestState {
  pending: boolean;
  result?: TxnSourceTest;
  error?: string;
}

export function SourcesSection({
  sources,
  error,
  canManage,
  onChanged,
  onImportStarted,
}: {
  sources: TxnSource[] | null;
  error: string | null;
  canManage: boolean;
  onChanged: () => void;
  onImportStarted: () => void;
}) {
  const [dialog, setDialog] = React.useState<{ open: boolean; source: TxnSource | null }>({
    open: false,
    source: null,
  });
  const [pulling, setPulling] = React.useState<TxnSource | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [tests, setTests] = React.useState<Record<string, TestState>>({});

  async function onTest(source: TxnSource) {
    setTests((prev) => ({ ...prev, [source.id]: { pending: true } }));
    try {
      const result = await apiCall("/api/txn-sources/{source_id}/test", "post", {
        params: { path: { source_id: source.id } },
      });
      setTests((prev) => ({ ...prev, [source.id]: { pending: false, result } }));
    } catch (e) {
      setTests((prev) => ({
        ...prev,
        [source.id]: { pending: false, error: getApiErrorMessage(e) },
      }));
    }
  }

  const columns = canManage ? 7 : 6;

  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle className="text-base">Sources</CardTitle>
            <CardDescription>
              Where transactions come from — CSV mapping templates and pullable APIs.
            </CardDescription>
          </div>
          {canManage && (
            <Button
              size="sm"
              variant="outline"
              className="shrink-0"
              onClick={() => setDialog({ open: true, source: null })}
            >
              <Plus className="mr-2 h-4 w-4" aria-hidden />
              New source
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {notice && (
          <p className="mx-6 mb-4 rounded-md border border-emerald-300/60 bg-emerald-50 px-4 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
            {notice}
          </p>
        )}
        {error !== null ? (
          <p className="px-6 pb-6 text-sm text-destructive">Failed to load sources: {error}</p>
        ) : sources === null ? (
          <p className="flex items-center gap-2 px-6 pb-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : sources.length === 0 ? (
          <p className="px-6 pb-6 text-sm text-muted-foreground">
            No sources yet{canManage ? " — create a CSV mapping template to start importing." : "."}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Name</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Active</TableHead>
                <TableHead>Schedule</TableHead>
                <TableHead>Credential</TableHead>
                <TableHead>Last pulled</TableHead>
                {canManage && <TableHead className="text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.map((s) => {
                const test = tests[s.id];
                return (
                  <React.Fragment key={s.id}>
                    <TableRow className={s.active ? undefined : "opacity-60"}>
                      <TableCell className="font-medium">{s.name}</TableCell>
                      <TableCell>
                        <Badge variant={s.kind === "api" ? "violet" : "info"}>{s.kind}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant={s.active ? "success" : "neutral"}>
                          {s.active ? "active" : "inactive"}
                        </Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono text-xs">
                        {s.schedule_cron ?? "—"}
                      </TableCell>
                      <TableCell>
                        {s.has_credential ? (
                          <span
                            className="inline-flex items-center gap-1 text-muted-foreground"
                            title="Credential stored (encrypted)"
                          >
                            <Lock className="h-3.5 w-3.5" aria-hidden />
                            <span className="text-xs">stored</span>
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatDateTime(s.last_pulled_at)}
                      </TableCell>
                      {canManage && (
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8"
                              disabled={test?.pending}
                              onClick={() => void onTest(s)}
                            >
                              {test?.pending ? (
                                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" aria-hidden />
                              ) : (
                                <FlaskConical className="mr-1 h-3.5 w-3.5" aria-hidden />
                              )}
                              Test
                            </Button>
                            {s.kind === "api" && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8"
                                onClick={() => {
                                  setNotice(null);
                                  setPulling(s);
                                }}
                              >
                                <DownloadCloud className="mr-1 h-3.5 w-3.5" aria-hidden />
                                Pull now
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              aria-label={`Edit ${s.name}`}
                              onClick={() => setDialog({ open: true, source: s })}
                            >
                              <Pencil className="h-4 w-4" aria-hidden />
                            </Button>
                          </div>
                        </TableCell>
                      )}
                    </TableRow>
                    {test && !test.pending && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={columns} className="bg-muted/40 py-3">
                          {test.error ? (
                            <p className="text-sm text-destructive">Test failed: {test.error}</p>
                          ) : test.result ? (
                            <div className="space-y-2">
                              <p className="flex items-center gap-2 text-sm">
                                <Badge variant={test.result.ok ? "success" : "destructive"}>
                                  {test.result.ok ? "ok" : "failed"}
                                </Badge>
                                <span className={test.result.ok ? "" : "text-destructive"}>
                                  {test.result.detail}
                                </span>
                              </p>
                              {test.result.sample && test.result.sample.length > 0 && (
                                <div className="overflow-x-auto rounded-md border bg-background">
                                  <Table>
                                    <TableHeader>
                                      <TableRow className="hover:bg-transparent">
                                        {SAMPLE_KEYS.map((c) => (
                                          <TableHead key={c.key}>{c.label}</TableHead>
                                        ))}
                                      </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                      {test.result.sample.map((row, i) => (
                                        <TableRow key={i}>
                                          {SAMPLE_KEYS.map((c) => (
                                            <TableCell
                                              key={c.key}
                                              className="whitespace-nowrap py-2 text-xs tabular-nums"
                                            >
                                              {sampleText(row[c.key])}
                                            </TableCell>
                                          ))}
                                        </TableRow>
                                      ))}
                                    </TableBody>
                                  </Table>
                                </div>
                              )}
                            </div>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>

      {dialog.open && (
        <SourceDialog
          source={dialog.source}
          onClose={() => setDialog({ open: false, source: null })}
          onSaved={() => {
            setDialog({ open: false, source: null });
            onChanged();
          }}
        />
      )}

      {pulling !== null && (
        <PullDialog
          source={pulling}
          onClose={() => setPulling(null)}
          onStarted={() => {
            setPulling(null);
            setNotice("Pull queued — track its progress in Imports above.");
            onImportStarted();
          }}
        />
      )}
    </Card>
  );
}
