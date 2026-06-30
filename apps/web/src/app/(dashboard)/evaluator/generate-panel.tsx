"use client";

import { CheckCircle2, Loader2, Sparkles } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { apiCall, getApiErrorMessage } from "@/lib/api";
import type { components } from "@voiceqa/shared-types";

type EvaluatorDraft = components["schemas"]["EvaluatorDraft"];
type GeneratedCriterion = components["schemas"]["GeneratedCriterion"];
type GeneratedField = components["schemas"]["GeneratedField"];

const SCORE_TYPE_LABELS: Record<string, string> = {
  pass_fail: "Pass / fail",
  scale_1_5: "Scale 1–5",
};

export function GeneratePanel({ projectId }: { projectId: string }) {
  const [description, setDescription] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState<EvaluatorDraft | null>(null);
  // Selection state keyed by item key; defaults to checked on generate.
  const [pickedCriteria, setPickedCriteria] = React.useState<Record<string, boolean>>({});
  const [pickedFields, setPickedFields] = React.useState<Record<string, boolean>>({});
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState<{ criteria: number; fields: number } | null>(null);

  async function onGenerate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!description.trim()) {
      setError("Describe what to check on your calls first.");
      return;
    }
    setPending(true);
    setError(null);
    setSaved(null);
    setSaveError(null);
    try {
      const result = await apiCall(
        "/api/projects/{project_id}/evaluator/generate",
        "post",
        {
          params: { path: { project_id: projectId } },
          body: { description: description.trim() },
        },
      );
      setDraft(result);
      setPickedCriteria(Object.fromEntries(result.criteria.map((c) => [c.key, true])));
      setPickedFields(Object.fromEntries(result.extraction_fields.map((f) => [f.key, true])));
    } catch (err) {
      setError(getApiErrorMessage(err));
    } finally {
      setPending(false);
    }
  }

  async function onSave() {
    if (draft === null) return;
    const criteria = draft.criteria.filter((c) => pickedCriteria[c.key]);
    const fields = draft.extraction_fields.filter((f) => pickedFields[f.key]);
    if (criteria.length === 0 && fields.length === 0) {
      setSaveError("Select at least one criterion or field to save.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await Promise.all([
        ...criteria.map((c, i) =>
          apiCall("/api/criteria", "post", {
            params: { query: { project_id: projectId } },
            body: {
              key: c.key,
              name: c.name,
              description: c.description,
              category: c.category,
              score_type: c.score_type,
              severity: c.severity,
              weight: c.weight,
              active: true,
              sort_order: i,
            },
          }),
        ),
        ...fields.map((f, i) =>
          apiCall("/api/extraction-fields", "post", {
            params: { query: { project_id: projectId } },
            body: {
              key: f.key,
              label: f.label,
              description: f.description ?? null,
              field_type: f.field_type,
              enum_options: f.enum_options ?? null,
              scope: "call",
              active: true,
              sort_order: i,
            },
          }),
        ),
      ]);
      setSaved({ criteria: criteria.length, fields: fields.length });
      setDraft(null);
      setDescription("");
    } catch (err) {
      setSaveError(getApiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 text-primary" aria-hidden />
            Generate criteria
          </CardTitle>
          <CardDescription>
            Describe what matters on these calls in plain language. We draft a rubric and extraction
            fields you can review before saving.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onGenerate} className="space-y-3">
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={5}
              placeholder="e.g. Confirm the agent greets the caller by name, verifies identity before discussing the account, discloses any fees, and never promises guaranteed returns."
              disabled={pending}
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <div className="flex items-center gap-3">
              <Button type="submit" disabled={pending}>
                {pending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Sparkles className="mr-2 h-4 w-4" aria-hidden />
                )}
                Generate criteria
              </Button>
              {pending && (
                <span className="text-sm text-muted-foreground">
                  Drafting your rubric — this can take up to 30 seconds…
                </span>
              )}
            </div>
          </form>
        </CardContent>
      </Card>

      {saved !== null && (
        <Card className="border-primary/40">
          <CardContent className="flex items-center gap-2 p-4 text-sm">
            <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden />
            <span>
              Saved {saved.criteria} criteri{saved.criteria === 1 ? "on" : "a"}
              {saved.fields > 0 &&
                ` and ${saved.fields} extraction field${saved.fields === 1 ? "" : "s"}`}
              . Find them on the Criteria and Extraction fields tabs.
            </span>
          </CardContent>
        </Card>
      )}

      {draft !== null && (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <CardTitle className="text-base">Review draft</CardTitle>
                <CardDescription>
                  Uncheck anything you don&apos;t want. Saving creates the selected items on this
                  project.
                </CardDescription>
              </div>
              <Button onClick={onSave} disabled={saving} className="shrink-0">
                {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
                Save selected
              </Button>
            </div>
            {saveError && <p className="text-sm text-destructive">{saveError}</p>}
          </CardHeader>
          <CardContent className="space-y-6">
            <section className="space-y-2">
              <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Criteria ({draft.criteria.length})
              </h3>
              {draft.criteria.length === 0 ? (
                <p className="text-sm text-muted-foreground">No criteria generated.</p>
              ) : (
                <ul className="divide-y rounded-md border">
                  {draft.criteria.map((c) => (
                    <DraftCriterionRow
                      key={c.key}
                      criterion={c}
                      checked={pickedCriteria[c.key] ?? false}
                      onToggle={(v) => setPickedCriteria((s) => ({ ...s, [c.key]: v }))}
                    />
                  ))}
                </ul>
              )}
            </section>

            <section className="space-y-2">
              <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Extraction fields ({draft.extraction_fields.length})
              </h3>
              {draft.extraction_fields.length === 0 ? (
                <p className="text-sm text-muted-foreground">No extraction fields generated.</p>
              ) : (
                <ul className="divide-y rounded-md border">
                  {draft.extraction_fields.map((f) => (
                    <DraftFieldRow
                      key={f.key}
                      field={f}
                      checked={pickedFields[f.key] ?? false}
                      onToggle={(v) => setPickedFields((s) => ({ ...s, [f.key]: v }))}
                    />
                  ))}
                </ul>
              )}
            </section>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function DraftCriterionRow({
  criterion,
  checked,
  onToggle,
}: {
  criterion: GeneratedCriterion;
  checked: boolean;
  onToggle: (v: boolean) => void;
}) {
  return (
    <li className="flex gap-3 p-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onToggle(e.target.checked)}
        className="mt-1 h-4 w-4 shrink-0 accent-[hsl(var(--primary))]"
        aria-label={`Include ${criterion.name}`}
      />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{criterion.name}</span>
          <code className="font-mono text-xs text-muted-foreground">{criterion.key}</code>
          <Badge variant="neutral">{criterion.category}</Badge>
          <Badge variant="secondary" className="font-normal">
            {SCORE_TYPE_LABELS[criterion.score_type] ?? criterion.score_type}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">{criterion.description}</p>
      </div>
    </li>
  );
}

function DraftFieldRow({
  field,
  checked,
  onToggle,
}: {
  field: GeneratedField;
  checked: boolean;
  onToggle: (v: boolean) => void;
}) {
  return (
    <li className="flex gap-3 p-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onToggle(e.target.checked)}
        className="mt-1 h-4 w-4 shrink-0 accent-[hsl(var(--primary))]"
        aria-label={`Include ${field.label}`}
      />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{field.label}</span>
          <code className="font-mono text-xs text-muted-foreground">{field.key}</code>
          <Badge variant="secondary" className="font-normal">
            {field.field_type}
          </Badge>
        </div>
        {field.description && <p className="text-sm text-muted-foreground">{field.description}</p>}
      </div>
    </li>
  );
}
