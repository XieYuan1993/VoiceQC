"use client";

import * as React from "react";
import { BookOpen, Tags } from "lucide-react";

import { cn } from "@/lib/utils";
import { TermsSection } from "../settings/terms-section";
import { KnowledgeManager } from "./knowledge-manager";
import { KnowledgeBaseSection } from "../settings/kb-section";

export function KnowledgeWorkspace({ projectId, canManage }: {
  projectId: string;
  canManage: boolean;
}) {
  const [tab, setTab] = React.useState<"knowledge" | "terms" | "documents">("knowledge");
  return (
    <div className="space-y-5">
      <div role="tablist" aria-label="知識庫分類" className="flex flex-wrap gap-4 border-b">
        {([
          { id: "knowledge", label: "知識卡片與常見問題", icon: BookOpen },
          { id: "terms", label: "熱詞管理", icon: Tags },
          { id: "documents", label: "參考資料", icon: BookOpen },
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
          : tab === "terms" ? <TermsSection projectId={projectId} canManage={canManage} />
          : <KnowledgeBaseSection projectId={projectId} canManage={canManage} />}
      </div>
    </div>
  );
}
