"use client";

import {
  KeyRound,
  Loader2,
  Mail,
  Pencil,
  Plus,
  ShieldOff,
} from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { apiCall, getApiErrorMessage } from "@/lib/api";
import { ROLES, roleBadgeVariant, roleLabel } from "@/lib/roles";
import type { AdminUser, AdminUserCreate, AdminUserUpdate } from "@/lib/types";

function parseCodes(text: string): string[] {
  return text
    .split(/[,\n]/)
    .map((c) => c.trim())
    .filter(Boolean);
}

function BrokerCodes({ codes }: { codes: string[] }) {
  if (codes.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {codes.map((c) => (
        <Badge key={c} variant="outline" className="font-normal tabular-nums">
          {c}
        </Badge>
      ))}
    </div>
  );
}

// ---- Create dialog -------------------------------------------------------

function CreateUserDialog({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [email, setEmail] = React.useState("");
  const [name, setName] = React.useState("");
  const [role, setRole] = React.useState<string>("reviewer");
  const [password, setPassword] = React.useState("");
  const [isActive, setIsActive] = React.useState(true);
  const [codesText, setCodesText] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const codes = parseCodes(codesText);
    if (!email.trim()) {
      setError("Email is required.");
      return;
    }
    if (role === "broker" && codes.length === 0) {
      setError("Broker accounts need at least one broker code.");
      return;
    }
    const body: AdminUserCreate = {
      email: email.trim(),
      name: name.trim() === "" ? null : name.trim(),
      role,
      // Absent password = SSO-only account.
      password: password.trim() === "" ? null : password,
      is_active: isActive,
      broker_codes: codes,
    };
    setPending(true);
    setError(null);
    try {
      await apiCall("/api/admin/users", "post", { body });
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
          <DialogTitle>Add user</DialogTitle>
          <DialogDescription>
            Leave the password blank for an SSO-only account (the user signs in
            with Microsoft).
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="nu-email">Email</Label>
            <Input
              id="nu-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="nu-name">Name (optional)</Label>
              <Input
                id="nu-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="nu-role">Role</Label>
              <Select
                id="nu-role"
                value={role}
                onChange={(e) => setRole(e.target.value)}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {roleLabel(r)}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="nu-password">Password (optional)</Label>
            <Input
              id="nu-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Blank = SSO-only"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="nu-codes">
              Broker codes{role === "broker" ? "" : " (optional)"}
            </Label>
            <Input
              id="nu-codes"
              value={codesText}
              onChange={(e) => setCodesText(e.target.value)}
              placeholder="Comma-separated, e.g. BRK01, BRK02"
            />
            {role === "broker" && (
              <p className="text-xs text-muted-foreground">
                Required for broker accounts — scopes the user to these
                extensions.
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Switch id="nu-active" checked={isActive} onCheckedChange={setIsActive} />
            <Label htmlFor="nu-active">Active</Label>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              Add user
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---- Edit dialog ---------------------------------------------------------

function EditUserDialog({
  user,
  onClose,
  onSaved,
}: {
  user: AdminUser;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = React.useState(user.name ?? "");
  const [role, setRole] = React.useState<string>(user.role);
  const [isActive, setIsActive] = React.useState(user.is_active);
  const [codesText, setCodesText] = React.useState(user.broker_codes.join(", "));
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const codes = parseCodes(codesText);
    if (role === "broker" && codes.length === 0) {
      setError("Broker accounts need at least one broker code.");
      return;
    }
    const body: AdminUserUpdate = {
      name: name.trim() === "" ? null : name.trim(),
      role,
      is_active: isActive,
      broker_codes: codes,
    };
    setPending(true);
    setError(null);
    try {
      await apiCall("/api/admin/users/{user_id}", "patch", {
        params: { path: { user_id: user.id } },
        body,
      });
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
          <DialogTitle>Edit user</DialogTitle>
          <DialogDescription>{user.email}</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="eu-name">Name</Label>
              <Input
                id="eu-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="eu-role">Role</Label>
              <Select
                id="eu-role"
                value={role}
                onChange={(e) => setRole(e.target.value)}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {roleLabel(r)}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="eu-codes">
              Broker codes{role === "broker" ? "" : " (optional)"}
            </Label>
            <Input
              id="eu-codes"
              value={codesText}
              onChange={(e) => setCodesText(e.target.value)}
              placeholder="Comma-separated"
            />
          </div>
          <div className="flex items-center gap-2">
            <Switch id="eu-active" checked={isActive} onCheckedChange={setIsActive} />
            <Label htmlFor="eu-active">Active</Label>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              Save changes
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---- Set-password dialog -------------------------------------------------

function SetPasswordDialog({
  user,
  onClose,
  onSaved,
}: {
  user: AdminUser;
  onClose: () => void;
  onSaved: (msg: string) => void;
}) {
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (password.trim().length === 0) {
      setError("Enter a password.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await apiCall("/api/admin/users/{user_id}/set-password", "post", {
        params: { path: { user_id: user.id } },
        body: { password },
      });
      onSaved(`Password set for ${user.email}.`);
    } catch (err) {
      setError(getApiErrorMessage(err));
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Set password</DialogTitle>
          <DialogDescription>
            Set a new password for {user.email}. They can still use SSO if it is
            enabled.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="sp-password">New password</Label>
            <Input
              id="sp-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              Set password
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---- Section -------------------------------------------------------------

export function UsersSection() {
  const [users, setUsers] = React.useState<AdminUser[] | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);
  const [editing, setEditing] = React.useState<AdminUser | null>(null);
  const [settingPw, setSettingPw] = React.useState<AdminUser | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  // Per-row inline error + busy state (toggle active, send reset).
  const [rowError, setRowError] = React.useState<{ id: string; msg: string } | null>(null);
  const [busyRow, setBusyRow] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      const list = await apiCall("/api/admin/users", "get", {});
      setUsers(list);
      setLoadError(null);
    } catch (e) {
      setLoadError(getApiErrorMessage(e));
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function toggleActive(user: AdminUser) {
    setBusyRow(user.id);
    setRowError(null);
    try {
      await apiCall("/api/admin/users/{user_id}", "patch", {
        params: { path: { user_id: user.id } },
        body: { is_active: !user.is_active } satisfies AdminUserUpdate,
      });
      await load();
    } catch (e) {
      // Surface 400s like "can't deactivate self" against the row.
      setRowError({ id: user.id, msg: getApiErrorMessage(e) });
    } finally {
      setBusyRow(null);
    }
  }

  async function sendReset(user: AdminUser) {
    setBusyRow(user.id);
    setRowError(null);
    setNotice(null);
    try {
      await apiCall("/api/admin/users/{user_id}/send-reset", "post", {
        params: { path: { user_id: user.id } },
      });
      setNotice(`Password-reset email queued for ${user.email}.`);
    } catch (e) {
      setRowError({ id: user.id, msg: getApiErrorMessage(e) });
    } finally {
      setBusyRow(null);
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle className="text-base">Users</CardTitle>
            <CardDescription>
              Accounts, roles and access. Brokers are scoped to their broker
              codes.
            </CardDescription>
          </div>
          <Button
            size="sm"
            onClick={() => {
              setNotice(null);
              setCreating(true);
            }}
          >
            <Plus className="mr-2 h-4 w-4" aria-hidden />
            Add user
          </Button>
        </div>
        {notice && (
          <p className="pt-2 text-sm text-emerald-700 dark:text-emerald-400">{notice}</p>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {loadError !== null ? (
          <p className="px-6 pb-6 text-sm text-destructive">
            Failed to load users: {loadError}
          </p>
        ) : users === null ? (
          <p className="flex items-center gap-2 px-6 pb-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : users.length === 0 ? (
          <p className="px-6 pb-6 text-sm text-muted-foreground">No users yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Email</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Sign-in</TableHead>
                <TableHead>Broker codes</TableHead>
                <TableHead>Active</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <React.Fragment key={u.id}>
                  <TableRow className={u.is_active ? undefined : "opacity-60"}>
                    <TableCell className="font-medium">{u.email ?? "—"}</TableCell>
                    <TableCell>{u.name ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant={roleBadgeVariant(u.role)}>{roleLabel(u.role)}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-1">
                        <Badge variant={u.has_password ? "neutral" : "info"} className="font-normal">
                          {u.has_password ? "Password" : "SSO-only"}
                        </Badge>
                        {u.locked && (
                          <Badge variant="destructive" className="font-normal">
                            Locked
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <BrokerCodes codes={u.broker_codes} />
                    </TableCell>
                    <TableCell>
                      <Switch
                        checked={u.is_active}
                        disabled={busyRow === u.id}
                        onCheckedChange={() => void toggleActive(u)}
                        aria-label={`${u.is_active ? "Deactivate" : "Activate"} ${u.email}`}
                      />
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          aria-label={`Edit ${u.email}`}
                          onClick={() => {
                            setRowError(null);
                            setEditing(u);
                          }}
                        >
                          <Pencil className="h-4 w-4" aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          aria-label={`Set password for ${u.email}`}
                          onClick={() => {
                            setRowError(null);
                            setSettingPw(u);
                          }}
                        >
                          <KeyRound className="h-4 w-4" aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          aria-label={`Send reset email to ${u.email}`}
                          disabled={busyRow === u.id}
                          onClick={() => void sendReset(u)}
                        >
                          <Mail className="h-4 w-4" aria-hidden />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                  {rowError?.id === u.id && (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={7} className="py-1">
                        <p className="flex items-center gap-1 text-sm text-destructive">
                          <ShieldOff className="h-4 w-4" aria-hidden />
                          {rowError.msg}
                        </p>
                      </TableCell>
                    </TableRow>
                  )}
                </React.Fragment>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      {creating && (
        <CreateUserDialog
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false);
            setNotice("User created.");
            void load();
          }}
        />
      )}
      {editing && (
        <EditUserDialog
          user={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      )}
      {settingPw && (
        <SetPasswordDialog
          user={settingPw}
          onClose={() => setSettingPw(null)}
          onSaved={(msg) => {
            setSettingPw(null);
            setNotice(msg);
            void load();
          }}
        />
      )}
    </Card>
  );
}
