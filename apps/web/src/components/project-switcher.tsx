"use client";

import { Check, ChevronsUpDown, Loader2, Plus } from "lucide-react";
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
import { PROJECT_COOKIE, type Project } from "@/lib/project";
import { cn } from "@/lib/utils";

/** Lowercase-hyphen slug derived from a free-text name. */
function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

function setActiveProject(id: string) {
  document.cookie = `${PROJECT_COOKIE}=${id}; path=/; max-age=31536000`;
}

export function ProjectSwitcher({
  projects,
  activeId,
}: {
  projects: Project[];
  activeId: string;
}) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);

  const active = projects.find((p) => p.id === activeId) ?? null;

  // Click-outside + Escape close the dropdown (mirrors ui/sheet.tsx behavior).
  React.useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function select(id: string) {
    setOpen(false);
    if (id === activeId) return;
    setActiveProject(id);
    router.refresh();
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-9 items-center gap-2 rounded-md border border-input bg-background px-2.5 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span aria-hidden className="h-2 w-2 rounded-full bg-primary" />
        <span className="max-w-[10rem] truncate">{active?.name ?? "Select project"}</span>
        <ChevronsUpDown aria-hidden className="h-4 w-4 text-muted-foreground" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute left-0 top-full z-50 mt-1 w-60 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-lg"
        >
          <div className="px-2 py-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Projects
          </div>
          {projects.map((p) => {
            const isActive = p.id === activeId;
            return (
              <button
                key={p.id}
                role="menuitemradio"
                aria-checked={isActive}
                type="button"
                onClick={() => select(p.id)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground",
                  isActive && "font-medium",
                )}
              >
                <Check
                  aria-hidden
                  className={cn("h-4 w-4 shrink-0", isActive ? "opacity-100 text-primary" : "opacity-0")}
                />
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                {p.is_default && (
                  <span className="shrink-0 text-xs text-muted-foreground">default</span>
                )}
              </button>
            );
          })}
          <div className="my-1 h-px bg-border" />
          <button
            role="menuitem"
            type="button"
            onClick={() => {
              setOpen(false);
              setDialogOpen(true);
            }}
            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            <Plus aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
            New project
          </button>
        </div>
      )}

      {dialogOpen && (
        <NewProjectDialog
          onClose={() => setDialogOpen(false)}
          onCreated={(p) => {
            setDialogOpen(false);
            setActiveProject(p.id);
            router.refresh();
          }}
        />
      )}
    </div>
  );
}

function NewProjectDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (project: Project) => void;
}) {
  const [name, setName] = React.useState("");
  const [slug, setSlug] = React.useState("");
  // Track whether the user hand-edited the slug; until then it follows the name.
  const [slugTouched, setSlugTouched] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  const effectiveSlug = slugTouched ? slug : slugify(name);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const trimmedName = name.trim();
    const finalSlug = (slugTouched ? slug : slugify(name)).trim();
    if (!trimmedName) {
      setError("Name is required.");
      return;
    }
    if (!finalSlug) {
      setError("Slug is required.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const project = await apiCall("/api/projects", "post", {
        body: { slug: finalSlug, name: trimmedName },
      });
      onCreated(project);
    } catch (err) {
      setError(getApiErrorMessage(err));
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>
            Each project has its own criteria, fields, terms and recordings.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="np-name">Name</Label>
            <Input
              id="np-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Retail Support"
              autoFocus
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="np-slug">Slug</Label>
            <Input
              id="np-slug"
              value={effectiveSlug}
              onChange={(e) => {
                setSlugTouched(true);
                setSlug(slugify(e.target.value));
              }}
              placeholder="retail-support"
              className="font-mono"
              required
            />
            <p className="text-xs text-muted-foreground">
              Lowercase letters, digits and hyphens. Used in URLs and exports.
            </p>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              Create project
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
