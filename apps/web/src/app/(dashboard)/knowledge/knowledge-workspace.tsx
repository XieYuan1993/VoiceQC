"use client";

import * as React from "react";
import { BookOpen, Tags } from "lucide-react";

import { cn } from "@/lib/utils";
import { TermsSection } from "../settings/terms-section";
import { KnowledgeManager } from "./knowledge-manager";
import { KnowledgeBaseSection } from "../settings/kb-section";

export function KnowledgeWorkspace({ projectId, canManage, canApprove }: {
  projectId: string;
  canManage: boolean;
  canApprove: boolean;
}) {
  const [tab, setTab] = React.useState<"knowledge" | "terms" | "documents">("knowledge");
  return (
    <div className="space-y-5">
      <div role="tablist" aria-label="Knowledge base sections" className="flex flex-wrap gap-4 border-b">
        {([
          { id: "knowledge", label: "Knowledge cards & FAQs", icon: BookOpen },
          { id: "terms", label: "Hotwords", icon: Tags },
          { id: "documents", label: "Reference documents", icon: BookOpen },
        ] as const).map(({ id, label, icon: Icon }) => (
          <button key={id} id={`knowledge-tab-${id}`} type="button" role="tab"
            aria-selected={tab === id} aria-controls={`knowledge-panel-${id}`}
            onClick={() => setTab(id)}
            className={cn("-mb-px inline-flex items-center gap-2 border-b-2 px-3 py-3 text-sm font-medium",
              tab === id ? "border-primary text-primary" : "border-transparent text-muted-foreground")}>
            <Icon aria-hidden className="h-4 w-4 shrink-0" />{label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`knowledge-panel-${tab}`} aria-labelledby={`knowledge-tab-${tab}`}>
        {tab === "knowledge"
          ? <KnowledgeManager projectId={projectId} canManage={canManage} />
          : tab === "terms" ? <TermsSection projectId={projectId} canManage={canManage} canApprove={canApprove} />
          : <KnowledgeBaseSection projectId={projectId} canManage={canManage} />}
      </div>
    </div>
  );
}
