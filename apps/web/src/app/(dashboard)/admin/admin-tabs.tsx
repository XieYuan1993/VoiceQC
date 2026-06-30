"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

import { AuditSection } from "./audit-section";
import { SsoSection } from "./sso-section";
import { UsageSection } from "./usage-section";
import { UsersSection } from "./users-section";

type TabId = "users" | "sso" | "audit" | "usage";

const TABS: ReadonlyArray<{ id: TabId; label: string }> = [
  { id: "users", label: "Users" },
  { id: "sso", label: "SSO" },
  { id: "audit", label: "Audit" },
  { id: "usage", label: "Usage" },
];

export function AdminTabs() {
  const [tab, setTab] = React.useState<TabId>("users");

  return (
    <div className="space-y-6">
      <div role="tablist" aria-label="Admin sections" className="flex gap-1 border-b">
        {TABS.map((t) => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              role="tab"
              type="button"
              aria-selected={active}
              onClick={() => setTab(t.id)}
              className={cn(
                "-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors",
                active
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {tab === "users" && <UsersSection />}
      {tab === "sso" && <SsoSection />}
      {tab === "audit" && <AuditSection />}
      {tab === "usage" && <UsageSection />}
    </div>
  );
}
