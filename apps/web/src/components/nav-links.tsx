"use client";

import {
  AudioLines,
  Inbox,
  Layers,
  LayoutDashboard,
  ListChecks,
  type LucideIcon,
  ReceiptText,
  Scale,
  Settings,
  ShieldCheck,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { hasTradeReconciliation } from "@/lib/project";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  pill?: string;
}

const WORKSPACE: ReadonlyArray<NavItem> = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/recordings", label: "Recordings", icon: AudioLines },
  { href: "/review", label: "Review queue", icon: Inbox },
  { href: "/agents", label: "Agent scorecards", icon: Users },
  { href: "/batches", label: "Batches", icon: Layers },
  { href: "/evaluator", label: "Evaluator", icon: ListChecks, pill: "AI" },
];

const MODULES: ReadonlyArray<NavItem> = [
  { href: "/transactions", label: "Transactions", icon: ReceiptText },
  { href: "/recon", label: "Reconciliation", icon: Scale },
];

const SYSTEM: ReadonlyArray<NavItem> = [
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/admin", label: "Admin", icon: ShieldCheck },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === "/dashboard" || pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavItemLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href as never}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2 rounded-md border-l-2 px-3 py-1.5 text-sm font-medium transition-colors",
        active
          ? "border-primary bg-secondary text-secondary-foreground"
          : "border-transparent text-muted-foreground hover:bg-muted/60 hover:text-foreground",
      )}
    >
      <Icon aria-hidden className="h-4 w-4 shrink-0" />
      <span className="flex-1">{item.label}</span>
      {item.pill && (
        <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium uppercase leading-none tracking-wide text-primary">
          {item.pill}
        </span>
      )}
    </Link>
  );
}

function NavGroup({
  label,
  items,
  pathname,
}: {
  label?: string;
  items: ReadonlyArray<NavItem>;
  pathname: string;
}) {
  return (
    <div className="space-y-1">
      {label && (
        <p className="px-3 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground/70">
          {label}
        </p>
      )}
      {items.map((item) => (
        <NavItemLink key={item.href} item={item} active={isActive(pathname, item.href)} />
      ))}
    </div>
  );
}

export function NavLinks({ modules }: { modules?: Record<string, unknown> }) {
  const pathname = usePathname() ?? "";
  const showModules = hasTradeReconciliation(modules);

  return (
    <nav className="flex flex-col gap-5" aria-label="Primary">
      <NavGroup label="Workspace" items={WORKSPACE} pathname={pathname} />
      {showModules && <NavGroup label="Modules" items={MODULES} pathname={pathname} />}
      <NavGroup items={SYSTEM} pathname={pathname} />
    </nav>
  );
}
