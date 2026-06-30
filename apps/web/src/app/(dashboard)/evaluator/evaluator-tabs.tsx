"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

import { ChecklistSection } from "../settings/checklist-section";
import { CriteriaSection } from "../settings/criteria-section";
import { ExtractionFieldsSection } from "../settings/extraction-fields-section";
import { KnowledgeBaseSection } from "../settings/kb-section";
import { TermsSection } from "../settings/terms-section";
import { GeneratePanel } from "./generate-panel";

type TabId = "criteria" | "fields" | "checklist" | "kb" | "terms" | "generate";

const TABS: ReadonlyArray<{ id: TabId; label: string }> = [
  { id: "criteria", label: "Criteria" },
  { id: "fields", label: "Extraction fields" },
  { id: "checklist", label: "Checklist" },
  { id: "kb", label: "Knowledge base" },
  { id: "terms", label: "Terms" },
  { id: "generate", label: "Generate" },
];

export function EvaluatorTabs({
  projectId,
  canManage,
}: {
  projectId: string;
  canManage: boolean;
}) {
  const [tab, setTab] = React.useState<TabId>("criteria");

  return (
    <div className="space-y-6">
      <div role="tablist" aria-label="Evaluator sections" className="flex gap-1 border-b">
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

      {/* Keep the project id flowing into each section so reads + creates scope
          to the active project. */}
      {tab === "criteria" && <CriteriaSection canManage={canManage} projectId={projectId} />}
      {tab === "fields" && <ExtractionFieldsSection canManage={canManage} projectId={projectId} />}
      {tab === "checklist" && <ChecklistSection canManage={canManage} projectId={projectId} />}
      {tab === "kb" && <KnowledgeBaseSection canManage={canManage} projectId={projectId} />}
      {tab === "terms" && <TermsSection canManage={canManage} projectId={projectId} />}
      {tab === "generate" && <GeneratePanel projectId={projectId} />}
    </div>
  );
}
