"use client";

import { Loader2, Pencil } from "lucide-react";
import * as React from "react";

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
import { formatDateTime } from "@/lib/format";
import type { AppSetting } from "@/lib/types";

type ValueKind = "boolean" | "number" | "string" | "json";

const ORDER_STATUS_OPTIONS = [
  "已委託",
  "成交",
  "部分成交",
  "已過期",
  "待報",
  "已撤單",
  "待報（保價）",
  "已修改",
  "待報（條件單）",
  "已拒絕",
];

const EXECUTION_TYPE_OPTIONS = [
  "",
  "TradeExec",
  "NewExec",
  "ExpiredExec",
  "ReplaceExec",
  "CanceledExec",
];

const SELECT_OPTIONS: Record<string, Array<{ value: string; label: string }>> = {
  "asr.provider": [
    { value: "tencent", label: "Tencent ASR" },
    { value: "qwen", label: "Qwen ASR" },
    { value: "gemini", label: "Gemini audio" },
    { value: "google", label: "Google STT" },
  ],
  "asr.language_mode": [
    { value: "auto", label: "Auto" },
    { value: "yue-Hant-HK", label: "Cantonese (HK Traditional)" },
    { value: "cmn-Hans-CN", label: "Mandarin (Simplified)" },
    { value: "en-US", label: "English (US)" },
  ],
  "asr.adaptation": [
    { value: "off", label: "Off" },
    { value: "stock_only", label: "Stock terms only" },
    { value: "all", label: "All glossary terms" },
  ],
};

function kindOf(value: unknown): ValueKind {
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return "number";
  if (typeof value === "string") return "string";
  return "json";
}

function preview(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function SettingDialog({
  setting,
  projectId,
  onClose,
  onSaved,
}: {
  setting: AppSetting;
  projectId?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const kind = kindOf(setting.value);
  const isReconFilters = setting.key === "recon.transaction_filters";
  const selectOptions = SELECT_OPTIONS[setting.key];
  const filterValue =
    setting.value !== null && typeof setting.value === "object"
      ? (setting.value as { order_statuses?: unknown; execution_types?: unknown })
      : {};
  const [orderStatuses, setOrderStatuses] = React.useState<string[]>(() =>
    Array.isArray(filterValue.order_statuses)
      ? filterValue.order_statuses.filter((x): x is string => typeof x === "string")
      : ORDER_STATUS_OPTIONS,
  );
  const [executionTypes, setExecutionTypes] = React.useState<string[]>(() =>
    Array.isArray(filterValue.execution_types)
      ? filterValue.execution_types.filter((x): x is string => typeof x === "string")
      : EXECUTION_TYPE_OPTIONS,
  );
  const [text, setText] = React.useState(() => {
    if (kind === "string") return setting.value as string;
    if (kind === "number") return String(setting.value);
    if (kind === "json") return JSON.stringify(setting.value, null, 2);
    return "";
  });
  const [boolValue, setBoolValue] = React.useState(
    kind === "boolean" ? (setting.value as boolean) : false,
  );
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    let next: unknown;
    if (selectOptions) {
      next = text;
    } else if (isReconFilters) {
      next = {
        order_statuses: orderStatuses,
        execution_types: executionTypes,
      };
    } else if (kind === "boolean") {
      next = boolValue;
    } else if (kind === "number") {
      const n = Number(text.trim());
      if (text.trim() === "" || !Number.isFinite(n)) {
        setError("Value must be a number.");
        return;
      }
      next = n;
    } else if (kind === "string") {
      next = text;
    } else {
      try {
        next = JSON.parse(text);
      } catch (err) {
        setError(`Invalid JSON: ${err instanceof Error ? err.message : String(err)}`);
        return;
      }
    }
    setPending(true);
    setError(null);
    try {
      await apiCall("/api/settings/{key}", "put", {
        params: { path: { key: setting.key }, query: { project_id: projectId || undefined } },
        body: { value: next },
      });
      onSaved();
    } catch (err) {
      // 400s carry the validator message (e.g. "retention.days: must be an
      // integer in [1, 3650]") — surface inline.
      setError(getApiErrorMessage(err));
      setPending(false);
    }
  }

  function toggleValue(values: string[], value: string, setter: (next: string[]) => void) {
    setter(values.includes(value) ? values.filter((v) => v !== value) : [...values, value]);
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="font-mono text-base">{setting.key}</DialogTitle>
          <DialogDescription>
            {kind === "json"
              ? "JSON value — validated before saving."
              : `${kind.charAt(0).toUpperCase()}${kind.slice(1)} value.`}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          {selectOptions ? (
            <div className="space-y-2">
              <Label htmlFor="setting-value">Value</Label>
              <Select
                id="setting-value"
                value={text}
                onChange={(e) => setText(e.target.value)}
              >
                {selectOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
          ) : isReconFilters ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>訂單狀態</Label>
                <div className="max-h-56 space-y-1.5 overflow-auto rounded-md border p-3">
                  {ORDER_STATUS_OPTIONS.map((value) => (
                    <label key={value} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={orderStatuses.includes(value)}
                        onChange={() => toggleValue(orderStatuses, value, setOrderStatuses)}
                        className="h-4 w-4 rounded border-input"
                      />
                      <span>{value}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <Label>執行類型</Label>
                <div className="max-h-56 space-y-1.5 overflow-auto rounded-md border p-3">
                  {EXECUTION_TYPE_OPTIONS.map((value) => (
                    <label key={value || "__blank"} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={executionTypes.includes(value)}
                        onChange={() => toggleValue(executionTypes, value, setExecutionTypes)}
                        className="h-4 w-4 rounded border-input"
                      />
                      <span>{value || "(blank)"}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          ) : kind === "boolean" ? (
            <div className="flex items-center gap-3">
              <Switch id="setting-value" checked={boolValue} onCheckedChange={setBoolValue} />
              <Label htmlFor="setting-value">{boolValue ? "Enabled" : "Disabled"}</Label>
            </div>
          ) : kind === "json" ? (
            <div className="space-y-2">
              <Label htmlFor="setting-value">Value (JSON)</Label>
              <Textarea
                id="setting-value"
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={8}
                className="font-mono text-xs"
                spellCheck={false}
              />
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="setting-value">Value</Label>
              <Input
                id="setting-value"
                type={kind === "number" ? "number" : "text"}
                step={kind === "number" ? "any" : undefined}
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
            </div>
          )}
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function AppSettingsSection({
  canManage,
  projectId,
}: {
  canManage: boolean;
  projectId?: string;
}) {
  const [settings, setSettings] = React.useState<AppSetting[] | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [editing, setEditing] = React.useState<AppSetting | null>(null);

  const load = React.useCallback(async () => {
    setSettings(null);
    try {
      const list = await apiCall("/api/settings", "get", {
        params: { query: { project_id: projectId || undefined } },
      });
      setSettings(list);
      setLoadError(null);
    } catch (e) {
      setLoadError(getApiErrorMessage(e));
    }
  }, [projectId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-base">App settings</CardTitle>
        <CardDescription>
          Pipeline and budget configuration. Every key is validated server-side.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {loadError !== null ? (
          <p className="px-6 pb-6 text-sm text-destructive">
            Failed to load settings: {loadError}
          </p>
        ) : settings === null ? (
          <p className="flex items-center gap-2 px-6 pb-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : settings.length === 0 ? (
          <p className="px-6 pb-6 text-sm text-muted-foreground">No settings found.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Key</TableHead>
                <TableHead>Value</TableHead>
                <TableHead>Updated</TableHead>
                {canManage && <TableHead className="text-right">Actions</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {settings.map((s) => (
                <TableRow key={s.key}>
                  <TableCell className="whitespace-nowrap font-mono text-xs">{s.key}</TableCell>
                  <TableCell className="max-w-[420px]">
                    <code
                      className="block truncate rounded bg-muted/60 px-1.5 py-0.5 font-mono text-xs"
                      title={preview(s.value)}
                    >
                      {preview(s.value)}
                    </code>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">
                    {formatDateTime(s.updated_at)}
                  </TableCell>
                  {canManage && (
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        aria-label={`Edit ${s.key}`}
                        onClick={() => setEditing(s)}
                      >
                        <Pencil className="h-4 w-4" aria-hidden />
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      {editing !== null && (
        <SettingDialog
          setting={editing}
          projectId={projectId}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      )}
    </Card>
  );
}
