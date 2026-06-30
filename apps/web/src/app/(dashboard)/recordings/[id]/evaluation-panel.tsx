"use client";

import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  HelpCircle,
  Info,
  Loader2,
  Minus,
  Pencil,
  Play,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import * as React from "react";

import { Badge, type BadgeProps } from "@/components/ui/badge";
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
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
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
import { formatDateTime, formatMs } from "@/lib/format";
import type { Evaluation, EvaluationResult, EvidenceItem, Trade } from "@/lib/types";
import { cn } from "@/lib/utils";

const POLL_MS = 5000;

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

const SEVERITY_BADGE: Record<string, BadgeProps["variant"]> = {
  info: "info",
  warning: "warning",
  critical: "destructive",
};

const REVIEW_BADGE: Record<string, BadgeProps["variant"]> = {
  unreviewed: "neutral",
  approved: "success",
  overridden: "orange",
};

const SIDE_BADGE: Record<string, BadgeProps["variant"]> = {
  buy: "success",
  sell: "destructive",
  amend: "warning",
  cancel: "neutral",
};

const SENTIMENT_BADGE: Record<string, BadgeProps["variant"]> = {
  positive: "success",
  neutral: "neutral",
  negative: "destructive",
  frustrated: "orange",
  mixed: "warning",
};

/** Transcript channel display label — "broker" reads as "agent" generically. */
function channelLabel(channel: string): string {
  return channel === "broker" ? "agent" : channel;
}

function scoreColor(score: number): string {
  if (score >= 80) return "text-emerald-600 dark:text-emerald-400";
  if (score >= 50) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

function formatTokens(n: number | null): string {
  if (n == null) return "—";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

function formatNumber(n: number | null): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(n);
}

/** "Yes"/"No"/string/number out of an unknown extracted-field value. */
function formatFieldValue(v: unknown): string {
  if (v == null || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "string" || typeof v === "number") return String(v);
  if (Array.isArray(v)) return v.map(formatFieldValue).join(", ");
  return JSON.stringify(v);
}

interface RiskFlag {
  key: string;
  severity: string;
  note: string | null;
}

// risk_flags is loosely typed in the OpenAPI schema (JSON column) — narrow
// defensively rather than trusting the LLM-written payload.
function toRiskFlag(raw: Record<string, unknown>, i: number): RiskFlag {
  return {
    key: typeof raw.key === "string" && raw.key ? raw.key : `flag ${i + 1}`,
    severity: typeof raw.severity === "string" ? raw.severity : "info",
    note: typeof raw.note === "string" && raw.note ? raw.note : null,
  };
}

interface ChecklistResultRow {
  key: string;
  label: string;
  required: boolean;
  covered: boolean;
  evidence_quote: string | null;
  approx_ms: number | null;
}

// checklist_results is a loosely-typed JSON column — narrow defensively.
function toChecklistResult(raw: Record<string, unknown>, i: number): ChecklistResultRow {
  const key = typeof raw.key === "string" && raw.key ? raw.key : `item_${i + 1}`;
  return {
    key,
    label: typeof raw.label === "string" && raw.label ? raw.label : key.replaceAll("_", " "),
    required: raw.required !== false,
    covered: raw.covered === true,
    evidence_quote:
      typeof raw.evidence_quote === "string" && raw.evidence_quote ? raw.evidence_quote : null,
    approx_ms: typeof raw.approx_ms === "number" ? raw.approx_ms : null,
  };
}

interface CorrectnessFinding {
  claim: string;
  verdict: "correct" | "incorrect" | "unsupported";
  kb_quote: string | null;
  evidence_quote: string | null;
  approx_ms: number | null;
}

// correctness_findings is a loosely-typed JSON column — narrow defensively.
function toCorrectnessFinding(raw: Record<string, unknown>, i: number): CorrectnessFinding {
  const verdict = raw.verdict;
  return {
    claim: typeof raw.claim === "string" && raw.claim ? raw.claim : `claim ${i + 1}`,
    verdict: verdict === "correct" || verdict === "incorrect" ? verdict : "unsupported",
    kb_quote: typeof raw.kb_quote === "string" && raw.kb_quote ? raw.kb_quote : null,
    evidence_quote:
      typeof raw.evidence_quote === "string" && raw.evidence_quote ? raw.evidence_quote : null,
    approx_ms: typeof raw.approx_ms === "number" ? raw.approx_ms : null,
  };
}

/** criterion_key -> score_type from the run's frozen criteria snapshot. */
function snapshotScoreTypes(ev: Evaluation): Map<string, string> {
  const m = new Map<string, string>();
  for (const c of ev.criteria_snapshot) {
    if (typeof c.key === "string" && typeof c.score_type === "string") {
      m.set(c.key, c.score_type);
    }
  }
  return m;
}

/** criterion_key -> position in the snapshot, to keep the configured order. */
function snapshotOrder(ev: Evaluation): Map<string, number> {
  const m = new Map<string, number>();
  ev.criteria_snapshot.forEach((c, i) => {
    if (typeof c.key === "string") m.set(c.key, i);
  });
  return m;
}

function resolveScoreType(result: EvaluationResult, snapshot: Map<string, string>): string {
  return (
    snapshot.get(result.criterion_key) ??
    (result.score != null && result.passed == null ? "scale_1_5" : "pass_fail")
  );
}

interface CallFieldRow {
  key: string;
  label: string;
  value: unknown;
  missing: boolean;
}

/** Every call-scope field configured for this run (from fields_snapshot),
 * paired with its extracted value — fields the model didn't capture are kept
 * and flagged so reviewers see what's missing, not just what was found. */
function callFieldRows(ev: Evaluation): CallFieldRow[] {
  const extracted = ev.extracted_call_fields as Record<string, unknown>;
  const seen = new Set<string>();
  const rows: CallFieldRow[] = [];
  const isMissing = (v: unknown) => v == null || v === "";
  for (const f of ev.fields_snapshot as Array<Record<string, unknown>>) {
    if (f.scope !== "call") continue;
    const key = typeof f.key === "string" ? f.key : "";
    if (key === "" || seen.has(key)) continue;
    seen.add(key);
    const label = typeof f.label === "string" && f.label ? f.label : key.replaceAll("_", " ");
    const value = extracted[key];
    rows.push({ key, label, value, missing: isMissing(value) });
  }
  // Surface any extracted value whose field is no longer in the snapshot.
  for (const [key, value] of Object.entries(extracted)) {
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({ key, label: key.replaceAll("_", " "), value, missing: isMissing(value) });
  }
  return rows;
}

// ---------------------------------------------------------------------------
// Atoms
// ---------------------------------------------------------------------------

function ScoreDonut({ score }: { score: number | null }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const frac = score == null ? 0 : Math.max(0, Math.min(100, score)) / 100;
  return (
    <div
      className="relative h-16 w-16 shrink-0"
      role="img"
      aria-label={
        score == null ? "No overall score" : `Overall score ${Math.round(score)} out of 100`
      }
    >
      <svg viewBox="0 0 64 64" className="h-16 w-16 -rotate-90">
        <circle cx="32" cy="32" r={r} fill="none" strokeWidth="6" className="stroke-muted" />
        {score != null && (
          <circle
            cx="32"
            cy="32"
            r={r}
            fill="none"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={`${frac * c} ${c}`}
            className={cn("stroke-current", scoreColor(score))}
          />
        )}
      </svg>
      <span
        className={cn(
          "absolute inset-0 flex items-center justify-center text-lg font-semibold tabular-nums",
          score == null ? "text-muted-foreground" : scoreColor(score),
        )}
      >
        {score == null ? "—" : Math.round(score)}
      </span>
    </div>
  );
}

/** Per-criterion contribution to the weighted overall score (matches the
 * worker's _overall_score): pass/fail -> 1/0, a 1-5 rating -> (n-1)/4, each
 * weighted; criteria the model could not judge are excluded. */
function scoreBreakdownRows(ev: Evaluation) {
  const weightByKey = new Map<string, number>();
  const typeByKey = new Map<string, string>();
  for (const c of ev.criteria_snapshot) {
    if (typeof c.key !== "string") continue;
    if (typeof c.weight === "number") weightByKey.set(c.key, c.weight);
    if (typeof c.score_type === "string") typeByKey.set(c.key, c.score_type);
  }
  let num = 0;
  let den = 0;
  const rows = ev.results.map((r) => {
    const weight = weightByKey.get(r.criterion_key) ?? 1;
    const scoreType =
      typeByKey.get(r.criterion_key) ??
      (r.score != null && r.passed == null ? "scale_1_5" : "pass_fail");
    let value: number | null = null;
    let resultLabel = "not judged";
    if (scoreType === "pass_fail" && r.passed != null) {
      value = r.passed ? 1 : 0;
      resultLabel = r.passed ? "pass" : "fail";
    } else if (scoreType === "scale_1_5" && r.score != null) {
      const s = Math.max(1, Math.min(5, Math.round(r.score)));
      value = (s - 1) / 4;
      resultLabel = `${s}/5`;
    }
    const included = value != null;
    if (included) {
      num += weight * value!;
      den += weight;
    }
    return {
      key: r.criterion_key,
      name: r.criterion_name,
      weight,
      value,
      resultLabel,
      contribution: included ? weight * value! : null,
      included,
    };
  });
  return { rows, num, den, total: den > 0 ? (num / den) * 100 : null };
}

function ScoreBreakdown({ ev }: { ev: Evaluation }) {
  const { rows, num, den, total } = scoreBreakdownRows(ev);
  return (
    <div className="rounded-lg border bg-muted/30 p-4">
      <p className="mb-3 text-xs text-muted-foreground">
        The overall score is a{" "}
        <span className="font-medium text-foreground">weighted average of this project&apos;s
        criteria</span>{" "}
        — each scored 0–100% (pass/fail → 100/0; a 1–5 rating maps onto the range), weighted by its
        importance. Criteria the model couldn&apos;t judge are excluded.
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-muted-foreground">
            <th className="pb-1.5 text-left font-medium">Criterion</th>
            <th className="pb-1.5 text-right font-medium">Weight</th>
            <th className="pb-1.5 text-right font-medium">Result</th>
            <th className="pb-1.5 text-right font-medium">Points</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className={cn("border-t", !r.included && "text-muted-foreground")}>
              <td className="py-1.5 pr-2">{r.name}</td>
              <td className="py-1.5 text-right tabular-nums">{r.weight}</td>
              <td className="py-1.5 text-right tabular-nums">
                {r.included ? (
                  <>
                    {r.resultLabel}{" "}
                    <span className="text-muted-foreground">
                      ({Math.round((r.value ?? 0) * 100)}%)
                    </span>
                  </>
                ) : (
                  <span className="italic">excluded</span>
                )}
              </td>
              <td className="py-1.5 text-right tabular-nums">
                {r.included ? (r.contribution ?? 0).toFixed(2) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 border-t pt-2 text-right text-sm tabular-nums">
        <span className="text-muted-foreground">
          {num.toFixed(2)} ÷ {den.toFixed(2)} × 100 ={" "}
        </span>
        <span className="font-semibold">{total != null ? total.toFixed(2) : "—"}</span>
        <span className="text-muted-foreground">
          {" "}
          → shown as {total != null ? Math.round(total) : "—"}
        </span>
      </p>
      <p className="mt-3 border-t pt-3 text-xs text-muted-foreground">
        Script <span className="font-medium text-foreground">adherence</span>
        {ev.checklist_score != null ? ` (${Math.round(ev.checklist_score)}%)` : ""} and answer{" "}
        <span className="font-medium text-foreground">accuracy</span>
        {ev.correctness_score != null ? ` (${Math.round(ev.correctness_score)}%)` : ""} are tracked
        separately below and are <span className="font-medium text-foreground">not</span> part of
        this score.
      </p>
    </div>
  );
}

const SEVERITY_NAME: Record<string, string> = {
  critical: "Critical",
  warning: "Warning",
  info: "Info",
};

/** A criterion result is a "concern" — worth the alarm colour — only when it
 * actually fell short: a failed pass/fail, or a low (<=2) 1-5 rating. */
function isConcern(result: EvaluationResult, scoreType: string): boolean {
  if (scoreType === "scale_1_5") {
    const s = result.override_score ?? result.score;
    return s != null && s <= 2;
  }
  return (result.override_passed ?? result.passed) === false;
}

/** Severity of the criterion (how serious a failure would be), shown as a
 * shape. Coloured only when the result is a concern; muted otherwise, so a red
 * icon never sits next to a PASS. */
function SeverityIcon({ severity, concern }: { severity: string | null; concern: boolean }) {
  const key = severity === "critical" || severity === "warning" ? severity : "info";
  const Icon = key === "critical" ? ShieldAlert : key === "warning" ? AlertTriangle : Info;
  const alarm =
    key === "critical"
      ? "text-red-600 dark:text-red-400"
      : key === "warning"
        ? "text-amber-600 dark:text-amber-400"
        : "text-blue-600 dark:text-blue-400";
  return (
    <span
      title={`${SEVERITY_NAME[key]} severity — how serious a failure of this check would be (not the result)`}
      className="inline-flex cursor-help"
    >
      <Icon
        className={cn("h-4 w-4 shrink-0", concern ? alarm : "text-muted-foreground/50")}
        aria-label={`${SEVERITY_NAME[key]} severity`}
      />
    </span>
  );
}

function PassFailPill({ passed, struck }: { passed: boolean | null; struck?: boolean }) {
  if (passed == null) {
    return (
      <Badge variant="neutral" className={cn(struck && "line-through opacity-60")}>
        N/A
      </Badge>
    );
  }
  return (
    <Badge
      variant={passed ? "success" : "destructive"}
      className={cn(struck && "line-through opacity-60")}
    >
      {passed ? "PASS" : "FAIL"}
    </Badge>
  );
}

function ScaleDots({ score, struck }: { score: number | null; struck?: boolean }) {
  if (score == null) {
    return (
      <Badge variant="neutral" className={cn(struck && "line-through opacity-60")}>
        N/A
      </Badge>
    );
  }
  const filled = Math.round(score);
  const dotColor = filled >= 4 ? "bg-emerald-500" : filled >= 3 ? "bg-amber-500" : "bg-red-500";
  return (
    <span
      className={cn("inline-flex items-center gap-1", struck && "opacity-60")}
      title={`${score} out of 5`}
    >
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          aria-hidden
          className={cn("h-2 w-2 rounded-full", i <= filled ? dotColor : "bg-muted")}
        />
      ))}
      <span
        className={cn(
          "ml-1 text-xs tabular-nums text-muted-foreground",
          struck && "line-through",
        )}
      >
        {score}/5
      </span>
    </span>
  );
}

function ResultScore({
  result,
  scoreType,
}: {
  result: EvaluationResult;
  scoreType: string;
}) {
  const isScale = scoreType === "scale_1_5";
  const overridden = result.overridden_at != null;
  if (!overridden) {
    return isScale ? (
      <ScaleDots score={result.score} />
    ) : (
      <PassFailPill passed={result.passed} />
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {isScale ? (
        <ScaleDots score={result.score} struck />
      ) : (
        <PassFailPill passed={result.passed} struck />
      )}
      <span aria-hidden className="text-muted-foreground">
        →
      </span>
      {isScale ? (
        <ScaleDots score={result.override_score ?? null} />
      ) : (
        <PassFailPill passed={result.override_passed ?? null} />
      )}
    </span>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
      {children}
    </h3>
  );
}

function EvidenceQuote({
  evidence,
  onJump,
}: {
  evidence: EvidenceItem;
  onJump: (ms: number) => void;
}) {
  const ms = evidence.approx_ms;
  const meta = (
    <span className="mb-0.5 flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
      {ms != null && <Play className="h-3 w-3" aria-hidden />}
      <span>{channelLabel(evidence.channel)}</span>
      {ms != null && <span className="tabular-nums normal-case">{formatMs(ms)}</span>}
    </span>
  );
  const quote = <span className="block italic">&ldquo;{evidence.quote}&rdquo;</span>;
  if (ms == null) {
    return (
      <div className="w-full rounded-md border-l-2 border-primary/40 bg-muted/50 px-3 py-1.5 text-xs">
        {meta}
        {quote}
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onJump(ms)}
      title="Play from here"
      className="block w-full rounded-md border-l-2 border-primary/40 bg-muted/50 px-3 py-1.5 text-left text-xs transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {meta}
      {quote}
    </button>
  );
}

function ConfidenceBar({ value }: { value: number | null }) {
  if (value == null) return <span className="text-muted-foreground">—</span>;
  const pct = Math.round(Math.max(0, Math.min(1, value <= 1 ? value : value / 100)) * 100);
  const color = pct >= 80 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2" title={`Confidence ${pct}%`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-muted-foreground">{pct}%</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dialogs
// ---------------------------------------------------------------------------

function RerunDialog({
  recordingId,
  onClose,
  onQueued,
}: {
  recordingId: string;
  onClose: () => void;
  onQueued: () => void;
}) {
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  async function onConfirm() {
    setPending(true);
    setError(null);
    try {
      await apiCall("/api/recordings/{recording_id}/evaluations", "post", {
        params: { path: { recording_id: recordingId } },
      });
      onQueued();
    } catch (e) {
      // 409 while busy / when there is no transcript yet.
      setError(getApiErrorMessage(e));
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Re-evaluate this call?</DialogTitle>
          <DialogDescription>
            Runs a fresh evaluation against the current criteria configuration and consumes LLM
            tokens. Previous runs are kept and stay selectable.
          </DialogDescription>
        </DialogHeader>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={onConfirm} disabled={pending}>
            {pending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
            )}
            Re-evaluate
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReviewDialog({
  evaluation,
  action,
  onClose,
  onSaved,
}: {
  evaluation: Evaluation;
  action: "approve" | "override";
  onClose: () => void;
  onSaved: (updated: Evaluation) => void;
}) {
  const [note, setNote] = React.useState(evaluation.review_note ?? "");
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const updated = await apiCall("/api/evaluations/{evaluation_id}/review", "post", {
        params: { path: { evaluation_id: evaluation.id } },
        body: { action, note: note.trim() === "" ? null : note.trim() },
      });
      onSaved(updated);
    } catch (err) {
      setError(getApiErrorMessage(err));
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {action === "approve" ? "Approve evaluation" : "Override evaluation"}
          </DialogTitle>
          <DialogDescription>
            {action === "approve"
              ? "Mark this run as reviewed and correct. The note is kept for the audit trail."
              : "Mark this run as overridden by a human reviewer. Explain what the model got wrong."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="review-note">Note {action === "approve" ? "(optional)" : ""}</Label>
            <Textarea
              id="review-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder={
                action === "approve" ? "Looks correct…" : "What was wrong with this run?"
              }
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              {action === "approve" ? "Approve" : "Override"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function OverrideResultDialog({
  evaluationId,
  result,
  scoreType,
  onClose,
  onSaved,
}: {
  evaluationId: string;
  result: EvaluationResult;
  scoreType: string;
  onClose: () => void;
  onSaved: (updated: Evaluation) => void;
}) {
  const isScale = scoreType === "scale_1_5";
  const effectivePassed = result.override_passed ?? result.passed;
  const effectiveScore = result.override_score ?? result.score;
  const [passed, setPassed] = React.useState<"pass" | "fail">(
    effectivePassed === false ? "fail" : "pass",
  );
  const [score, setScore] = React.useState(
    String(Math.min(5, Math.max(1, Math.round(effectiveScore ?? 3)))),
  );
  const [note, setNote] = React.useState(result.override_note ?? "");
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const updated = await apiCall(
        "/api/evaluations/{evaluation_id}/results/{criterion_key}/override",
        "post",
        {
          params: {
            path: { evaluation_id: evaluationId, criterion_key: result.criterion_key },
          },
          body: isScale
            ? { score: Number(score), note: note.trim() === "" ? null : note.trim() }
            : { passed: passed === "pass", note: note.trim() === "" ? null : note.trim() },
        },
      );
      onSaved(updated);
    } catch (err) {
      setError(getApiErrorMessage(err));
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Override result</DialogTitle>
          <DialogDescription>
            {result.criterion_name} — replaces the model&apos;s verdict for this run only. The
            original stays visible, struck through.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          {isScale ? (
            <div className="space-y-2">
              <Label htmlFor="override-score">Score (1–5)</Label>
              <Select
                id="override-score"
                value={score}
                onChange={(e) => setScore(e.target.value)}
                wrapperClassName="w-32"
              >
                {["1", "2", "3", "4", "5"].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="override-passed">Verdict</Label>
              <Select
                id="override-passed"
                value={passed}
                onChange={(e) => setPassed(e.target.value === "fail" ? "fail" : "pass")}
                wrapperClassName="w-40"
              >
                <option value="pass">Pass</option>
                <option value="fail">Fail</option>
              </Select>
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="override-note">Note (optional)</Label>
            <Textarea
              id="override-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder="Why this verdict is being corrected"
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              Save override
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Scorecard
// ---------------------------------------------------------------------------

function ScorecardRow({
  result,
  scoreType,
  canReview,
  onOverride,
  onJump,
}: {
  result: EvaluationResult;
  scoreType: string;
  canReview: boolean;
  onOverride: () => void;
  onJump: (ms: number) => void;
}) {
  const overridden = result.overridden_at != null;
  return (
    <div className="rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 items-center gap-2">
          <SeverityIcon severity={result.severity} concern={isConcern(result, scoreType)} />
          <span className="text-sm font-medium">{result.criterion_name}</span>
          {overridden && (
            <Badge variant="orange" className="shrink-0">
              overridden
            </Badge>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ResultScore result={result} scoreType={scoreType} />
          {canReview && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
              onClick={onOverride}
            >
              <Pencil className="mr-1 h-3 w-3" aria-hidden />
              Override
            </Button>
          )}
        </div>
      </div>
      {result.rationale && (
        <p className="mt-2 text-sm text-muted-foreground">{result.rationale}</p>
      )}
      {overridden && result.override_note && (
        <p className="mt-2 rounded-md bg-orange-50 px-3 py-1.5 text-sm text-orange-900 dark:bg-orange-950/40 dark:text-orange-200">
          <span className="font-medium">Override note:</span> {result.override_note}
        </p>
      )}
      {result.evidence.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {result.evidence.map((ev, i) => (
            <EvidenceQuote key={i} evidence={ev} onJump={onJump} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trades
// ---------------------------------------------------------------------------

function TradesTable({ trades, onJump }: { trades: Trade[]; onJump: (ms: number) => void }) {
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="w-8">#</TableHead>
          <TableHead>Stock</TableHead>
          <TableHead>Side</TableHead>
          <TableHead className="text-right">Quantity</TableHead>
          <TableHead className="text-right">Price</TableHead>
          <TableHead>Client</TableHead>
          <TableHead>Time</TableHead>
          <TableHead>Confidence</TableHead>
          <TableHead className="w-8" aria-label="Evidence" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {trades.map((t) => {
          const isOpen = expanded.has(t.id);
          return (
            <React.Fragment key={t.id}>
              <TableRow>
                <TableCell className="tabular-nums text-muted-foreground">{t.seq}</TableCell>
                <TableCell>
                  <span className="font-medium tabular-nums">{t.stock_code ?? "—"}</span>
                  {t.stock_name_raw && (
                    <span className="block text-xs text-muted-foreground">
                      {t.stock_name_raw}
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={SIDE_BADGE[t.side] ?? "neutral"}>{t.side}</Badge>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatNumber(t.quantity)}
                </TableCell>
                <TableCell className="whitespace-nowrap text-right tabular-nums">
                  {t.price != null ? formatNumber(t.price) : ""}
                  <span className={cn("text-xs text-muted-foreground", t.price != null && "ml-1")}>
                    {t.price_type}
                  </span>
                </TableCell>
                <TableCell>
                  {t.client_name_raw ?? "—"}
                  {t.client_account_raw && (
                    <span className="block text-xs tabular-nums text-muted-foreground">
                      {t.client_account_raw}
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  {t.time_in_call_ms != null ? (
                    <button
                      type="button"
                      onClick={() => onJump(t.time_in_call_ms!)}
                      title="Play from here"
                      className="inline-flex items-center gap-1 tabular-nums text-primary hover:underline"
                    >
                      <Play className="h-3 w-3" aria-hidden />
                      {formatMs(t.time_in_call_ms)}
                    </button>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell>
                  <ConfidenceBar value={t.confidence} />
                </TableCell>
                <TableCell>
                  {t.evidence_quote && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      aria-label={isOpen ? "Hide evidence quote" : "Show evidence quote"}
                      aria-expanded={isOpen}
                      onClick={() => toggle(t.id)}
                    >
                      {isOpen ? (
                        <ChevronDown className="h-4 w-4" aria-hidden />
                      ) : (
                        <ChevronRight className="h-4 w-4" aria-hidden />
                      )}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
              {isOpen && t.evidence_quote && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={9} className="bg-muted/30 py-2">
                    <p className="text-xs italic text-muted-foreground">
                      &ldquo;{t.evidence_quote}&rdquo;
                    </p>
                  </TableCell>
                </TableRow>
              )}
            </React.Fragment>
          );
        })}
      </TableBody>
    </Table>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export function EvaluationPanel({
  recordingId,
  recordingStatus,
  canReview,
  onJump,
  onRecordingChanged,
}: {
  recordingId: string;
  recordingStatus: string;
  canReview: boolean;
  /** Seek the audio player and flash the matching transcript segment. */
  onJump: (ms: number) => void;
  /** A re-run was queued — parent should refresh the recording status. */
  onRecordingChanged: () => void;
}) {
  const [evals, setEvals] = React.useState<Evaluation[] | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  // null = follow the latest run; set when the user picks an older run.
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [rerunOpen, setRerunOpen] = React.useState(false);
  const [review, setReview] = React.useState<"approve" | "override" | null>(null);
  const [overrideTarget, setOverrideTarget] = React.useState<EvaluationResult | null>(null);
  const [detailTab, setDetailTab] = React.useState<"scoring" | "extracted">("scoring");
  const [showBreakdown, setShowBreakdown] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const list = await apiCall("/api/recordings/{recording_id}/evaluations", "get", {
        params: { path: { recording_id: recordingId } },
      });
      setEvals(list);
      setLoadError(null);
    } catch (e) {
      setLoadError(getApiErrorMessage(e));
    }
  }, [recordingId]);

  // Fetch on mount and on every pipeline-status change (an evaluation
  // finishing flips the recording back to completed); poll while evaluating.
  React.useEffect(() => {
    void load();
    if (recordingStatus !== "evaluating") return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [load, recordingStatus]);

  function replaceEval(updated: Evaluation) {
    setEvals((prev) =>
      prev === null ? prev : prev.map((e) => (e.id === updated.id ? updated : e)),
    );
  }

  const evaluating = recordingStatus === "evaluating";
  const selected =
    evals !== null && evals.length > 0
      ? (selectedId !== null ? evals.find((e) => e.id === selectedId) : undefined) ?? evals[0]
      : null;

  // -- Empty / loading states -----------------------------------------------

  let body: React.ReactNode = null;
  if (loadError !== null && evals === null) {
    body = (
      <p className="text-sm text-destructive">Failed to load evaluations: {loadError}</p>
    );
  } else if (evals === null) {
    body = (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading evaluation…
      </p>
    );
  } else if (selected === null) {
    body = evaluating ? (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Evaluating… results appear here automatically.
      </p>
    ) : recordingStatus === "completed" ? (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-muted-foreground">Not evaluated.</p>
        {canReview && (
          <Button size="sm" onClick={() => setRerunOpen(true)}>
            <Sparkles className="mr-2 h-4 w-4" aria-hidden />
            Evaluate
          </Button>
        )}
      </div>
    ) : (
      <p className="text-sm text-muted-foreground">
        No evaluation yet — the recording has to finish processing first.
      </p>
    );
  } else if (selected.status === "running") {
    body = (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Run #{selected.run_seq} is evaluating… results appear here automatically.
      </p>
    );
  } else if (selected.status === "failed") {
    body = (
      <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm">
        <p className="font-medium text-destructive">Run #{selected.run_seq} failed</p>
        {selected.error && (
          <p className="mt-1 break-words text-xs text-destructive/90">{selected.error}</p>
        )}
      </div>
    );
  } else {
    const scoreTypes = snapshotScoreTypes(selected);
    const order = snapshotOrder(selected);
    const results = [...selected.results].sort(
      (a, b) =>
        (order.get(a.criterion_key) ?? Number.MAX_SAFE_INTEGER) -
          (order.get(b.criterion_key) ?? Number.MAX_SAFE_INTEGER) ||
        a.criterion_key.localeCompare(b.criterion_key),
    );
    const flags = selected.risk_flags.map(toRiskFlag);
    const checklist = selected.checklist_results.map(toChecklistResult);
    const requiredChecklist = checklist.filter((c) => c.required);
    const coveredRequired = requiredChecklist.filter((c) => c.covered).length;
    const correctness = selected.correctness_findings.map(toCorrectnessFinding);
    const checkableCorr = correctness.filter((c) => c.verdict !== "unsupported");
    const correctCorr = checkableCorr.filter((c) => c.verdict === "correct").length;
    const callFields = callFieldRows(selected);
    const missingFieldCount = callFields.filter((f) => f.missing).length;

    body = (
      <div className="space-y-6">
        {/* Header: donut + meta + review actions */}
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <ScoreDonut score={selected.overall_score} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={REVIEW_BADGE[selected.review_status] ?? "neutral"}>
                {selected.review_status}
              </Badge>
              {selected.llm_model && (
                <span className="font-mono text-xs text-muted-foreground">
                  {selected.llm_model}
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {formatTokens(selected.input_tokens)} in · {formatTokens(selected.output_tokens)}{" "}
              out · evaluated {formatDateTime(selected.completed_at ?? selected.created_at)}
            </p>
            {selected.results.length > 0 && (
              <button
                type="button"
                onClick={() => setShowBreakdown((v) => !v)}
                aria-expanded={showBreakdown}
                className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
              >
                {showBreakdown ? (
                  <ChevronDown className="h-3 w-3" aria-hidden />
                ) : (
                  <ChevronRight className="h-3 w-3" aria-hidden />
                )}
                How is this score calculated?
              </button>
            )}
            {selected.reviewed_at && (
              <p className="mt-1 text-xs text-muted-foreground">
                Reviewed {formatDateTime(selected.reviewed_at)}
                {selected.review_note ? ` — ${selected.review_note}` : ""}
              </p>
            )}
          </div>
          {canReview && (
            <div className="flex shrink-0 items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => setReview("approve")}>
                <Check className="mr-2 h-4 w-4" aria-hidden />
                Approve
              </Button>
              <Button size="sm" variant="outline" onClick={() => setReview("override")}>
                Override
              </Button>
            </div>
          )}
        </div>

        {showBreakdown && selected.results.length > 0 && <ScoreBreakdown ev={selected} />}

        {/* Summary */}
        {selected.summary && (
          <div className="space-y-2">
            <SectionHeading>Summary</SectionHeading>
            <p className="text-sm leading-relaxed">{selected.summary}</p>
          </div>
        )}

        {/* Call insights — sentiment / intent / complaint / topics / follow-ups */}
        {(selected.sentiment_label ||
          selected.customer_intent ||
          selected.is_complaint ||
          selected.topics.length > 0 ||
          selected.follow_up_actions.length > 0) && (
          <div className="space-y-3">
            <SectionHeading>Call insights</SectionHeading>
            <div className="flex flex-wrap items-center gap-2">
              {selected.sentiment_label && (
                <Badge variant={SENTIMENT_BADGE[selected.sentiment_label] ?? "neutral"}>
                  {selected.sentiment_label}
                  {selected.sentiment_score != null &&
                    selected.sentiment_label !== "neutral" && (
                      <span className="ml-1 tabular-nums opacity-80">
                        {selected.sentiment_score > 0 ? "+" : ""}
                        {selected.sentiment_score.toFixed(1)}
                      </span>
                    )}
                </Badge>
              )}
              {selected.is_complaint && (
                <Badge variant="destructive">
                  Complaint
                  {selected.complaint_category ? `: ${selected.complaint_category}` : ""}
                </Badge>
              )}
              {selected.customer_intent && (
                <span className="text-sm">
                  <span className="text-muted-foreground">Intent:</span>{" "}
                  {selected.customer_intent}
                </span>
              )}
            </div>
            {selected.topics.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                {selected.topics.map((t) => (
                  <Badge key={t} variant="neutral" className="font-normal">
                    {t}
                  </Badge>
                ))}
              </div>
            )}
            {selected.follow_up_actions.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Follow-up actions</p>
                <ul className="list-disc space-y-0.5 pl-5 text-sm">
                  {selected.follow_up_actions.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Detail tabs: scoring (the rubric) vs extracted (structured data) */}
        <div>
          <div className="flex gap-5 border-b" role="tablist" aria-label="Evaluation detail">
            {(["scoring", "extracted"] as const).map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={detailTab === t}
                onClick={() => setDetailTab(t)}
                className={cn(
                  "-mb-px border-b-2 px-1 pb-2 text-sm font-medium transition-colors",
                  detailTab === t
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {t === "scoring" ? "Scoring" : "Extracted"}
              </button>
            ))}
          </div>

          {detailTab === "scoring" ? (
            <div className="mt-4 space-y-6">
              {/* Risk flags */}
              {flags.length > 0 && (
                <div className="space-y-2">
                  <SectionHeading>Risk flags</SectionHeading>
                  <ul className="space-y-1.5">
                    {flags.map((f, i) => (
                      <li key={`${f.key}-${i}`} className="flex flex-wrap items-center gap-2">
                        <Badge variant={SEVERITY_BADGE[f.severity] ?? "neutral"}>
                          {f.key.replaceAll("_", " ")}
                        </Badge>
                        {f.note && (
                          <span className="text-sm text-muted-foreground">{f.note}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {/* Script adherence (checklist) */}
              {checklist.length > 0 && (
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <SectionHeading>Script adherence</SectionHeading>
                    {selected.checklist_score != null && (
                      <span className="tabular-nums">
                        <span
                          className={cn(
                            "text-sm font-semibold",
                            scoreColor(selected.checklist_score),
                          )}
                        >
                          {Math.round(selected.checklist_score)}% covered
                        </span>
                        {requiredChecklist.length > 0 && (
                          <span className="ml-1.5 text-xs text-muted-foreground">
                            ({coveredRequired} of {requiredChecklist.length} required)
                          </span>
                        )}
                      </span>
                    )}
                  </div>
                  <ul className="space-y-1.5">
                    {checklist.map((c) => (
                      <li key={c.key} className="flex items-start gap-2 text-sm">
                        {c.covered ? (
                          <Check
                            className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400"
                            aria-label="covered"
                          />
                        ) : c.required ? (
                          <X
                            className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400"
                            aria-label="not covered"
                          />
                        ) : (
                          <Minus
                            className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                            aria-label="not covered (optional)"
                          />
                        )}
                        <div className="min-w-0">
                          <span
                            className={cn(!c.covered && !c.required && "text-muted-foreground")}
                          >
                            {c.label}
                          </span>
                          {!c.required && (
                            <span className="ml-1.5 text-xs text-muted-foreground">
                              (optional)
                            </span>
                          )}
                          {c.covered &&
                            c.evidence_quote &&
                            (c.approx_ms != null ? (
                              <button
                                type="button"
                                onClick={() => onJump(c.approx_ms!)}
                                title="Play from here"
                                className="mt-0.5 flex items-start gap-1 text-left text-xs italic text-muted-foreground hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              >
                                <Play
                                  className="mt-0.5 h-3 w-3 shrink-0 not-italic"
                                  aria-hidden
                                />
                                <span>&ldquo;{c.evidence_quote}&rdquo;</span>
                              </button>
                            ) : (
                              <span className="block text-xs italic text-muted-foreground">
                                &ldquo;{c.evidence_quote}&rdquo;
                              </span>
                            ))}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {/* Answer correctness — RAG against the knowledge base */}
              {correctness.length > 0 && (
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <SectionHeading>Answer correctness</SectionHeading>
                    {selected.correctness_score != null && (
                      <span className="tabular-nums">
                        <span
                          className={cn(
                            "text-sm font-semibold",
                            scoreColor(selected.correctness_score),
                          )}
                        >
                          {Math.round(selected.correctness_score)}% accurate
                        </span>
                        {checkableCorr.length > 0 && (
                          <span className="ml-1.5 text-xs text-muted-foreground">
                            ({correctCorr} of {checkableCorr.length} checkable)
                          </span>
                        )}
                      </span>
                    )}
                  </div>
                  <ul className="space-y-2.5">
                    {correctness.map((c, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm">
                        {c.verdict === "correct" ? (
                          <Check
                            className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400"
                            aria-label="correct"
                          />
                        ) : c.verdict === "incorrect" ? (
                          <X
                            className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400"
                            aria-label="incorrect"
                          />
                        ) : (
                          <HelpCircle
                            className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                            aria-label="not in the knowledge base"
                          />
                        )}
                        <div className="min-w-0 space-y-1">
                          <span
                            className={cn(c.verdict === "unsupported" && "text-muted-foreground")}
                          >
                            {c.claim}
                          </span>
                          {c.evidence_quote &&
                            (c.approx_ms != null ? (
                              <button
                                type="button"
                                onClick={() => onJump(c.approx_ms!)}
                                title="Play from here"
                                className="flex items-start gap-1 text-left text-xs italic text-muted-foreground hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              >
                                <Play className="mt-0.5 h-3 w-3 shrink-0 not-italic" aria-hidden />
                                <span>&ldquo;{c.evidence_quote}&rdquo;</span>
                              </button>
                            ) : (
                              <span className="block text-xs italic text-muted-foreground">
                                &ldquo;{c.evidence_quote}&rdquo;
                              </span>
                            ))}
                          {c.kb_quote && (
                            <span className="flex items-start gap-1.5 rounded-md border-l-2 border-primary/30 bg-muted/40 px-2 py-1 text-xs text-muted-foreground">
                              <BookOpen className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                              <span>{c.kb_quote.replace(/^[-•–*]\s+/, "")}</span>
                            </span>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {/* Scorecard */}
              <div className="space-y-2">
                <SectionHeading>Scorecard</SectionHeading>
                {results.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No criterion results in this run.</p>
                ) : (
                  <div className="space-y-3">
                    {results.map((r) => (
                      <ScorecardRow
                        key={r.criterion_key}
                        result={r}
                        scoreType={resolveScoreType(r, scoreTypes)}
                        canReview={canReview}
                        onOverride={() => setOverrideTarget(r)}
                        onJump={onJump}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="mt-4 space-y-6">
              {/* Call fields — every configured field; missing ones flagged */}
              {callFields.length > 0 && (
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <SectionHeading>Call fields</SectionHeading>
                    {missingFieldCount > 0 && (
                      <span className="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
                        <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                        {missingFieldCount} not captured
                      </span>
                    )}
                  </div>
                  <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {callFields.map((f) => (
                      <div
                        key={f.key}
                        className={cn(
                          "rounded-md border px-2.5 py-1.5",
                          f.missing
                            ? "border-amber-300 bg-amber-50 dark:border-amber-900/60 dark:bg-amber-950/30"
                            : "bg-muted/40",
                        )}
                      >
                        <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
                          {f.label}
                        </dt>
                        <dd
                          className={cn(
                            "text-sm",
                            f.missing && "italic text-amber-700 dark:text-amber-300",
                          )}
                        >
                          {f.missing ? "Not captured" : formatFieldValue(f.value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
              {/* Extracted trades — only present with the trade-reconciliation module */}
              {selected.trades.length > 0 && (
                <div className="space-y-2">
                  <SectionHeading>Extracted trades</SectionHeading>
                  <div className="rounded-lg border">
                    <TradesTable trades={selected.trades} onJump={onJump} />
                  </div>
                </div>
              )}
              {callFields.length === 0 && selected.trades.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No structured data extracted from this call. Add extraction fields in the
                  Evaluator, then re-evaluate.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  const hasRuns = evals !== null && evals.length > 0;

  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base">Evaluation</CardTitle>
            <CardDescription>
              LLM evaluation against this project&apos;s criteria.
            </CardDescription>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {hasRuns && evals.length > 1 && (
              <Select
                value={selected?.id ?? ""}
                onChange={(e) => setSelectedId(e.target.value)}
                wrapperClassName="w-56"
                aria-label="Select evaluation run"
                className="h-9"
              >
                {evals.map((ev) => (
                  <option key={ev.id} value={ev.id}>
                    Run #{ev.run_seq} · {formatDateTime(ev.created_at)} · {ev.status}
                  </option>
                ))}
              </Select>
            )}
            {canReview && hasRuns && (
              <Button
                size="sm"
                variant="outline"
                disabled={evaluating}
                onClick={() => setRerunOpen(true)}
              >
                <RefreshCw className="mr-2 h-4 w-4" aria-hidden />
                Re-evaluate
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>{body}</CardContent>

      {rerunOpen && (
        <RerunDialog
          recordingId={recordingId}
          onClose={() => setRerunOpen(false)}
          onQueued={() => {
            setRerunOpen(false);
            setSelectedId(null); // follow the new run when it lands
            onRecordingChanged();
            void load();
          }}
        />
      )}

      {review !== null && selected !== null && (
        <ReviewDialog
          evaluation={selected}
          action={review}
          onClose={() => setReview(null)}
          onSaved={(updated) => {
            setReview(null);
            replaceEval(updated);
          }}
        />
      )}

      {overrideTarget !== null && selected !== null && (
        <OverrideResultDialog
          evaluationId={selected.id}
          result={overrideTarget}
          scoreType={resolveScoreType(overrideTarget, snapshotScoreTypes(selected))}
          onClose={() => setOverrideTarget(null)}
          onSaved={(updated) => {
            setOverrideTarget(null);
            replaceEval(updated);
          }}
        />
      )}
    </Card>
  );
}
