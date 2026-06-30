"use client";

import { CheckCircle2, Loader2, Plug, Plus, Trash2, XCircle } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { apiCall, getApiErrorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { ROLES, roleLabel } from "@/lib/roles";
import type { GroupRoleMapping, SsoConfig, SsoConfigIn, SsoTest } from "@/lib/types";

export function SsoSection() {
  const [config, setConfig] = React.useState<SsoConfig | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  // Form state (initialised from config once loaded).
  const [enabled, setEnabled] = React.useState(false);
  const [tenantId, setTenantId] = React.useState("");
  const [clientId, setClientId] = React.useState("");
  const [clientSecret, setClientSecret] = React.useState("");
  const [domainsText, setDomainsText] = React.useState("");
  const [mappings, setMappings] = React.useState<GroupRoleMapping[]>([]);
  const [autoProvision, setAutoProvision] = React.useState(false);
  const [defaultRole, setDefaultRole] = React.useState("reviewer");

  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState<string | null>(null);
  const [saveOk, setSaveOk] = React.useState(false);
  const [testing, setTesting] = React.useState(false);
  const [testResult, setTestResult] = React.useState<SsoTest | null>(null);

  const applyConfig = React.useCallback((c: SsoConfig) => {
    setConfig(c);
    setEnabled(c.enabled);
    setTenantId(c.tenant_id ?? "");
    setClientId(c.client_id ?? "");
    setClientSecret("");
    setDomainsText(c.allowed_email_domains.join(", "));
    setMappings(c.group_role_mappings.map((m) => ({ ...m })));
    setAutoProvision(c.auto_provision);
    setDefaultRole(c.default_role);
  }, []);

  const load = React.useCallback(async () => {
    try {
      const c = await apiCall("/api/admin/sso", "get", {});
      applyConfig(c);
      setLoadError(null);
    } catch (e) {
      setLoadError(getApiErrorMessage(e));
    }
  }, [applyConfig]);

  React.useEffect(() => {
    void load();
  }, [load]);

  function buildBody(): SsoConfigIn {
    const domains = domainsText
      .split(/[,\n]/)
      .map((d) => d.trim().toLowerCase())
      .filter(Boolean);
    const cleanMappings = mappings
      .map((m) => ({ group_id: m.group_id.trim(), role: m.role }))
      .filter((m) => m.group_id !== "");
    const body: SsoConfigIn = {
      enabled,
      tenant_id: tenantId.trim() === "" ? null : tenantId.trim(),
      client_id: clientId.trim() === "" ? null : clientId.trim(),
      allowed_email_domains: domains,
      group_role_mappings: cleanMappings,
      auto_provision: autoProvision,
      default_role: defaultRole,
    };
    // Only send the secret when the admin typed one; blank keeps the stored one.
    if (clientSecret.trim() !== "") body.client_secret = clientSecret;
    return body;
  }

  async function onSave(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setSaveOk(false);
    try {
      const updated = await apiCall("/api/admin/sso", "put", { body: buildBody() });
      applyConfig(updated);
      setSaveOk(true);
    } catch (err) {
      setSaveError(getApiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function onTest() {
    setTesting(true);
    setTestResult(null);
    try {
      // Tests the stored tenant — save first if you changed the tenant id.
      const res = await apiCall("/api/admin/sso/test", "post", {});
      setTestResult(res);
    } catch (err) {
      setTestResult({ ok: false, detail: getApiErrorMessage(err) });
    } finally {
      setTesting(false);
    }
  }

  function updateMapping(i: number, patch: Partial<GroupRoleMapping>) {
    setMappings((prev) => prev.map((m, idx) => (idx === i ? { ...m, ...patch } : m)));
  }

  if (loadError !== null) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-destructive">
          Failed to load SSO config: {loadError}
        </CardContent>
      </Card>
    );
  }
  if (config === null) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle className="text-base">Microsoft Entra ID (SSO)</CardTitle>
            <CardDescription>
              Connect Microsoft Entra ID so staff sign in with their work
              account. Changes take effect within a minute.
            </CardDescription>
          </div>
          <span className="text-xs text-muted-foreground">
            Updated {formatDateTime(config.updated_at)}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSave} className="space-y-5">
          <div className="flex items-center gap-2">
            <Switch id="sso-enabled" checked={enabled} onCheckedChange={setEnabled} />
            <Label htmlFor="sso-enabled">Enable single sign-on</Label>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="sso-tenant">Directory (tenant) ID</Label>
              <Input
                id="sso-tenant"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                placeholder="e.g. 00000000-0000-0000-0000-000000000000 or organizations"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="sso-client">Application (client) ID</Label>
              <Input
                id="sso-client"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                placeholder="App registration client ID"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="sso-secret">Client secret</Label>
            <Input
              id="sso-secret"
              type="password"
              autoComplete="off"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              placeholder={config.has_secret ? "Leave blank to keep current secret" : "Client secret value"}
            />
            <p className="text-xs text-muted-foreground">
              Stored encrypted at rest (AES-256-GCM).
              {config.has_secret && " A secret is currently saved."}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="sso-domains">Allowed email domains</Label>
            <Input
              id="sso-domains"
              value={domainsText}
              onChange={(e) => setDomainsText(e.target.value)}
              placeholder="Comma-separated, e.g. example.com"
            />
            <p className="text-xs text-muted-foreground">
              Leave empty to allow any domain the tenant authenticates.
            </p>
          </div>

          <div className="space-y-2">
            <Label>Group → role mappings</Label>
            <p className="text-xs text-muted-foreground">
              When the token carries a matching group claim, the user&apos;s role
              is set from the first match.
            </p>
            <div className="space-y-2">
              {mappings.length === 0 && (
                <p className="text-sm text-muted-foreground">No mappings.</p>
              )}
              {mappings.map((m, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    value={m.group_id}
                    onChange={(e) => updateMapping(i, { group_id: e.target.value })}
                    placeholder="Group object ID"
                    aria-label={`Group id ${i + 1}`}
                  />
                  <Select
                    value={m.role}
                    onChange={(e) => updateMapping(i, { role: e.target.value })}
                    wrapperClassName="w-52 shrink-0"
                    aria-label={`Role for mapping ${i + 1}`}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {roleLabel(r)}
                      </option>
                    ))}
                  </Select>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-10 w-10 shrink-0 text-destructive hover:text-destructive"
                    aria-label={`Remove mapping ${i + 1}`}
                    onClick={() => setMappings((prev) => prev.filter((_, idx) => idx !== i))}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </Button>
                </div>
              ))}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setMappings((prev) => [...prev, { group_id: "", role: "reviewer" }])
              }
            >
              <Plus className="mr-2 h-4 w-4" aria-hidden />
              Add mapping
            </Button>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex items-center gap-2">
              <Switch
                id="sso-autoprovision"
                checked={autoProvision}
                onCheckedChange={setAutoProvision}
              />
              <Label htmlFor="sso-autoprovision">
                Auto-provision new users on first sign-in
              </Label>
            </div>
            <div className="space-y-2">
              <Label htmlFor="sso-defaultrole">Default role (when no mapping matches)</Label>
              <Select
                id="sso-defaultrole"
                value={defaultRole}
                onChange={(e) => setDefaultRole(e.target.value)}
                wrapperClassName="max-w-xs"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {roleLabel(r)}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {testResult && (
            <p
              className={
                "flex items-center gap-2 text-sm " +
                (testResult.ok
                  ? "text-emerald-700 dark:text-emerald-400"
                  : "text-destructive")
              }
            >
              {testResult.ok ? (
                <CheckCircle2 className="h-4 w-4" aria-hidden />
              ) : (
                <XCircle className="h-4 w-4" aria-hidden />
              )}
              {testResult.detail}
              {testResult.issuer ? ` — issuer: ${testResult.issuer}` : ""}
            </p>
          )}
          {saveError && <p className="text-sm text-destructive">{saveError}</p>}
          {saveOk && (
            <p className="text-sm text-emerald-700 dark:text-emerald-400">
              SSO settings saved.
            </p>
          )}

          <div className="flex items-center gap-2">
            <Button type="submit" disabled={saving}>
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              Save
            </Button>
            <Button type="button" variant="outline" onClick={onTest} disabled={testing}>
              {testing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Plug className="mr-2 h-4 w-4" aria-hidden />
              )}
              Test connection
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
