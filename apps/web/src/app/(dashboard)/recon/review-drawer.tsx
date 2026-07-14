"use client";

import { Check, ExternalLink, Link2, Loader2, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { apiCall, getApiErrorMessage } from "@/lib/api";
import { formatDateTime, formatMs } from "@/lib/format";
import type { ReconItem, RecordingList, TxnList } from "@/lib/types";
import { cn } from "@/lib/utils";

import { MatchStatusBadge, SeverityBadge, formatScore } from "./badges";

// ---------------------------------------------------------------------------
// score_breakdown narrowing — the generated type is a loose dict; the worker
// writes {components, weights, stock_note, penalty, capped?, split_fill?}.
// ---------------------------------------------------------------------------

const COMPONENT_ORDER = ["stock", "side", "quantity", "price", "client", "time"] as const;

interface Breakdown {
  components: Record<string, number> | null;
  weights: Record<string, number> | null;
  stockNote: string | null;
  penalty: string | null;
  capped: string | null;
  splitFill: string | null;
  conflicts: Conflict[];
}

interface Conflict {
  field: string;
  transaction: unknown;
  recording: unknown;
}

// Top candidate calls the engine stored on an unmatched-trade item.
interface Candidate {
  instruction_id: string | null;
  recording_id: string;
  score: number | null;
  stock_code: string | null;
  side: string | null;
  quantity: number | null;
  price: number | null;
  client: string | null;
  broker_name: string | null;
  original_filename: string | null;
  call_started_at: string | null;
  conflicts: Conflict[];
}

const UNMATCHED_REASON_LABELS: Record<string, string> = {
  no_broker_recordings_day: "This broker has no recordings on the transaction day.",
  no_recordings_in_window: "The broker has calls that day, but none in the matching time window.",
  no_matching_recording: "Calls exist in the time window, but none satisfy the matching rules.",
};

function conflicts(raw: unknown): Conflict[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (value): value is Conflict =>
      typeof value === "object" && value !== null && typeof (value as Conflict).field === "string",
  );
}

function numRecord(v: unknown): Record<string, number> | null {
  if (v === null || typeof v !== "object" || Array.isArray(v)) return null;
  const out: Record<string, number> = {};
  for (const [k, val] of Object.entries(v)) {
    if (typeof val === "number") out[k] = val;
  }
  return Object.keys(out).length > 0 ? out : null;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

function parseBreakdown(raw: { [key: string]: unknown }): Breakdown {
  return {
    components: numRecord(raw.components),
    weights: numRecord(raw.weights),
    stockNote: str(raw.stock_note),
    penalty: str(raw.penalty),
    capped: str(raw.capped),
    splitFill: str(raw.split_fill),
    conflicts: conflicts(raw.conflict_fields),
  };
}

function formatNumber(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(n);
}

// Component score -> traffic-light tone for the comparison cells.
function matchTone(v: number | undefined): string {
  if (v === undefined) return "";
  if (v >= 0.999)
    return "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200";
  if (v <= 0.001) return "bg-red-50 text-red-900 dark:bg-red-950/40 dark:text-red-200";
  return "bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200";
}

function barColor(v: number): string {
  if (v >= 0.999) return "bg-emerald-500";
  if (v <= 0.001) return "bg-red-500";
  return "bg-amber-500";
}

function CompareRow({
  label,
  left,
  right,
  score,
}: {
  label: string;
  left: React.ReactNode;
  right: React.ReactNode;
  score: number | undefined;
}) {
  const tone = matchTone(score);
  return (
    <>
      <div className="py-2 pr-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className={cn("rounded-md px-2 py-2 text-sm", tone)}>{left}</div>
      <div className={cn("rounded-md px-2 py-2 text-sm", tone)}>{right}</div>
    </>
  );
}

function ScoreBreakdownBars({ breakdown }: { breakdown: Breakdown }) {
  const { components, weights } = breakdown;
  if (components === null) return null;
  return (
    <div className="space-y-2">
      {COMPONENT_ORDER.filter((k) => components[k] !== undefined).map((k) => {
        const value = components[k];
        const weight = weights?.[k];
        return (
          <div key={k} className="grid grid-cols-[5.5rem_1fr_3rem_3rem] items-center gap-2 text-xs">
            <span className="capitalize text-muted-foreground">{k}</span>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div
                className={cn("h-full rounded-full", barColor(value))}
                style={{ width: `${Math.round(value * 100)}%` }}
              />
            </div>
            <span className="text-right tabular-nums">{value.toFixed(2)}</span>
            <span className="text-right tabular-nums text-muted-foreground">
              {weight !== undefined ? `w ${Math.round(weight * 100)}%` : ""}
            </span>
          </div>
        );
      })}
      {(breakdown.stockNote || breakdown.penalty || breakdown.capped || breakdown.splitFill) && (
        <ul className="space-y-1 pt-1 text-xs">
          {breakdown.stockNote && (
            <li className="text-muted-foreground">Stock: {breakdown.stockNote}</li>
          )}
          {breakdown.splitFill && (
            <li className="text-blue-700 dark:text-blue-300">Split fill: {breakdown.splitFill}</li>
          )}
          {breakdown.penalty && (
            <li className="text-amber-700 dark:text-amber-300">Penalty: {breakdown.penalty}</li>
          )}
          {breakdown.capped && (
            <li className="text-red-700 dark:text-red-300">Capped: {breakdown.capped}</li>
          )}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Manual link picker — recordings from the run's trade date.
// ---------------------------------------------------------------------------

function ManualLinkPicker({
  tradeDate,
  pending,
  onLink,
}: {
  tradeDate: string;
  pending: boolean;
  onLink: (recordingId: string) => void;
}) {
  const [recordings, setRecordings] = React.useState<RecordingList | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [picked, setPicked] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const list = await apiCall("/api/recordings", "get", {
          params: { query: { call_date: tradeDate, page_size: 50 } },
        });
        if (!cancelled) setRecordings(list);
      } catch (e) {
        if (!cancelled) setError(getApiErrorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tradeDate]);

  if (error !== null) {
    return <p className="text-sm text-destructive">Failed to load recordings: {error}</p>;
  }
  if (recordings === null) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading recordings…
      </p>
    );
  }
  if (recordings.items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No recordings on {tradeDate} to link.</p>
    );
  }
  return (
    <div className="space-y-3">
      <div className="max-h-56 space-y-1 overflow-y-auto rounded-md border p-2">
        {recordings.items.map((r) => (
          <label
            key={r.id}
            className={cn(
              "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted/60",
              picked === r.id && "bg-muted",
            )}
          >
            <input
              type="radio"
              name="manual-link-recording"
              checked={picked === r.id}
              onChange={() => setPicked(r.id)}
              className="accent-primary"
            />
            <span className="min-w-0 flex-1 truncate" title={r.original_filename}>
              {r.original_filename}
            </span>
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {r.broker_ext ? `ext ${r.broker_ext} · ` : ""}
              {formatDateTime(r.call_started_at)}
            </span>
          </label>
        ))}
      </div>
      <Button
        size="sm"
        disabled={picked === null || pending}
        onClick={() => picked !== null && onLink(picked)}
      >
        {pending ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <Link2 className="mr-2 h-4 w-4" aria-hidden />
        )}
        Link selected recording
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Transaction picker — booked trades from the run's trade date. Used to link a
// "recording without txn" item (a call) to the trade it placed.
// ---------------------------------------------------------------------------

function TransactionPicker({
  tradeDate,
  pending,
  onLink,
}: {
  tradeDate: string;
  pending: boolean;
  onLink: (transactionId: string) => void;
}) {
  const [txns, setTxns] = React.useState<TxnList | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [picked, setPicked] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const list = await apiCall("/api/transactions", "get", {
          params: { query: { trade_date: tradeDate, page_size: 100 } },
        });
        if (!cancelled) setTxns(list);
      } catch (e) {
        if (!cancelled) setError(getApiErrorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tradeDate]);

  if (error !== null) {
    return <p className="text-sm text-destructive">Failed to load trades: {error}</p>;
  }
  if (txns === null) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading trades…
      </p>
    );
  }
  if (txns.items.length === 0) {
    return <p className="text-sm text-muted-foreground">No booked trades on {tradeDate} to link.</p>;
  }
  return (
    <div className="space-y-3">
      <div className="max-h-56 space-y-1 overflow-y-auto rounded-md border p-2">
        {txns.items.map((t) => (
          <label
            key={t.id}
            className={cn(
              "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted/60",
              picked === t.id && "bg-muted",
            )}
          >
            <input
              type="radio"
              name="manual-link-txn"
              checked={picked === t.id}
              onChange={() => setPicked(t.id)}
              className="accent-primary"
            />
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium tabular-nums">
                {[
                  t.stock_code,
                  t.side,
                  t.quantity != null ? new Intl.NumberFormat("en-US").format(t.quantity) : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              {t.client_name && <span className="text-muted-foreground"> · {t.client_name}</span>}
            </span>
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {t.ext_txn_id ?? ""}
            </span>
          </label>
        ))}
      </div>
      <Button
        size="sm"
        disabled={picked === null || pending}
        onClick={() => picked !== null && onLink(picked)}
      >
        {pending ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <Link2 className="mr-2 h-4 w-4" aria-hidden />
        )}
        Link selected trade
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Drawer
// ---------------------------------------------------------------------------

export function ReviewDrawer({
  item,
  runTradeDate,
  canReview,
  onClose,
  onUpdated,
}: {
  item: ReconItem;
  runTradeDate: string;
  canReview: boolean;
  onClose: () => void;
  onUpdated: (item: ReconItem) => void;
}) {
  const [note, setNote] = React.useState(item.review_note ?? "");
  const [pending, setPending] = React.useState<"confirm" | "reject" | "link" | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [showLink, setShowLink] = React.useState(false);
  const [showLinkTxn, setShowLinkTxn] = React.useState(false);

  const breakdown = parseBreakdown(item.score_breakdown);
  const comp = breakdown.components;
  const txn = item.transaction;
  const instr = item.instruction;
  const rec = item.recording;
  const candidates = (item.score_breakdown as { candidates?: Candidate[] })?.candidates ?? [];
  const unmatchedReason = str(item.score_breakdown.unmatched_reason);

  async function onDecide(action: "confirm" | "reject") {
    setPending(action);
    setError(null);
    try {
      const updated = await apiCall(
        action === "confirm" ? "/api/recon/items/{item_id}/confirm" : "/api/recon/items/{item_id}/reject",
        "post",
        { params: { path: { item_id: item.id } }, body: { note: note.trim() || null } },
      );
      onUpdated(updated);
    } catch (e) {
      setError(getApiErrorMessage(e));
    } finally {
      setPending(null);
    }
  }

  async function onManualLink(recordingId: string, instructionId?: string) {
    setPending("link");
    setError(null);
    try {
      const updated = await apiCall("/api/recon/items/{item_id}/manual-link", "post", {
        params: { path: { item_id: item.id } },
        body: {
          recording_id: recordingId,
          trade_instruction_id: instructionId ?? null,
          note: note.trim() || null,
        },
      });
      setShowLink(false);
      onUpdated(updated);
    } catch (e) {
      setError(getApiErrorMessage(e));
    } finally {
      setPending(null);
    }
  }

  // Link a "recording without txn" call to the booked trade it placed.
  async function onLinkTransaction(transactionId: string) {
    if (rec === null) return;
    setPending("link");
    setError(null);
    try {
      const updated = await apiCall("/api/recon/items/{item_id}/manual-link", "post", {
        params: { path: { item_id: item.id } },
        body: {
          recording_id: rec.id,
          transaction_id: transactionId,
          trade_instruction_id: instr?.id ?? null,
          note: note.trim() || null,
        },
      });
      setShowLinkTxn(false);
      onUpdated(updated);
    } catch (e) {
      setError(getApiErrorMessage(e));
    } finally {
      setPending(null);
    }
  }

  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle className="flex flex-wrap items-center gap-2">
            Review item
            <SeverityBadge severity={item.severity} />
            <MatchStatusBadge status={item.match_status} />
            {item.score != null && (
              <span className="text-sm font-normal text-muted-foreground">
                score {formatScore(item.score)}
              </span>
            )}
          </SheetTitle>
        </SheetHeader>

        {/* Side-by-side comparison */}
        <div className="grid grid-cols-[6rem_1fr_1fr] gap-x-2 gap-y-1">
          <div />
          <p className="px-2 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Transaction (booked)
          </p>
          <p className="px-2 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Call instruction
          </p>

          <CompareRow
            label="Stock"
            score={comp?.stock}
            left={
              txn ? (
                <>
                  <span className="font-medium tabular-nums">{txn.stock_code ?? "—"}</span>
                  {txn.stock_name && (
                    <span className="block text-xs opacity-80">{txn.stock_name}</span>
                  )}
                </>
              ) : (
                "—"
              )
            }
            right={
              instr ? (
                <>
                  <span className="font-medium tabular-nums">{instr.stock_code ?? "—"}</span>
                  {instr.stock_name_raw && (
                    <span className="block text-xs opacity-80">{instr.stock_name_raw}</span>
                  )}
                </>
              ) : (
                "—"
              )
            }
          />
          <CompareRow
            label="Side"
            score={comp?.side}
            left={txn ? txn.side : "—"}
            right={instr ? instr.side : "—"}
          />
          <CompareRow
            label="Quantity"
            score={comp?.quantity}
            left={<span className="tabular-nums">{txn ? formatNumber(txn.quantity) : "—"}</span>}
            right={
              <span className="tabular-nums">{instr ? formatNumber(instr.quantity) : "—"}</span>
            }
          />
          <CompareRow
            label="Price"
            score={comp?.price}
            left={<span className="tabular-nums">{txn ? formatNumber(txn.price) : "—"}</span>}
            right={
              instr ? (
                <span className="tabular-nums">
                  {formatNumber(instr.price)}
                  <span className="ml-1 text-xs opacity-70">{instr.price_type}</span>
                </span>
              ) : (
                "—"
              )
            }
          />
          <CompareRow
            label="Client"
            score={comp?.client}
            left={
              txn ? (
                <>
                  {txn.client_name ?? "—"}
                  {txn.client_account && (
                    <span className="block text-xs tabular-nums opacity-80">
                      {txn.client_account}
                    </span>
                  )}
                </>
              ) : (
                "—"
              )
            }
            right={
              instr ? (
                <>
                  {instr.client_name_raw ?? "—"}
                  {instr.client_account_raw && (
                    <span className="block text-xs tabular-nums opacity-80">
                      {instr.client_account_raw}
                    </span>
                  )}
                </>
              ) : (
                "—"
              )
            }
          />
          <CompareRow
            label="Time"
            score={comp?.time}
            left={
              txn ? (
                <>
                  <span className="block text-xs">ordered {formatDateTime(txn.ordered_at)}</span>
                  <span className="block text-xs">executed {formatDateTime(txn.executed_at)}</span>
                  {txn.broker_code && (
                    <span className="block text-xs opacity-80">broker {txn.broker_code}</span>
                  )}
                </>
              ) : (
                "—"
              )
            }
            right={
              rec ? (
                <>
                  <span className="block text-xs">call {formatDateTime(rec.call_started_at)}</span>
                  {instr?.time_in_call_ms != null && (
                    <span className="block text-xs">at {formatMs(instr.time_in_call_ms)} in call</span>
                  )}
                  {rec.broker_ext && (
                    <span className="block text-xs opacity-80">ext {rec.broker_ext}</span>
                  )}
                </>
              ) : (
                "—"
              )
            }
          />
        </div>

        <p className="text-xs text-muted-foreground">
          Green = matches · amber = close · red = contradicts (per scoring component).
        </p>

        {/* Recording link / empty-side explanations */}
        {rec ? (
          <p className="text-sm">
            <Link
              href={`/recordings/${rec.id}`}
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              {rec.original_filename}
            </Link>
            {instr === null && (
              <span className="block pt-1 text-xs text-muted-foreground">
                No trade instruction was extracted from this call.
              </span>
            )}
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">
            No recording matched this transaction
            {item.item_type === "txn_no_recording" ? " — link one manually below if you find it." : "."}
          </p>
        )}
        {txn === null && item.item_type === "recording_no_txn" && (
          <p className="text-sm text-muted-foreground">
            No booked transaction was found for this call.
          </p>
        )}

        {unmatchedReason && UNMATCHED_REASON_LABELS[unmatchedReason] && (
          <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm">
            {UNMATCHED_REASON_LABELS[unmatchedReason]}
          </div>
        )}

        {breakdown.conflicts.length > 0 && (
          <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">
            <p className="font-medium">Conflicting fields</p>
            {breakdown.conflicts.map((conflict) => (
              <p key={conflict.field} className="mt-1 font-mono text-xs">
                {conflict.field}: {String(conflict.transaction ?? "unknown")} vs {String(conflict.recording ?? "unknown")}
              </p>
            ))}
          </div>
        )}

        {/* Score breakdown */}
        {comp !== null && (
          <div className="space-y-2 rounded-md border p-4">
            <h3 className="text-sm font-medium">Score breakdown</h3>
            <ScoreBreakdownBars breakdown={breakdown} />
          </div>
        )}

        {/* Existing decision */}
        {(item.review_note || item.reviewed_at) && (
          <div className="rounded-md border bg-muted/40 px-4 py-3 text-sm">
            {item.review_note && <p>{item.review_note}</p>}
            {item.reviewed_at && (
              <p className="mt-1 text-xs text-muted-foreground">
                Reviewed {formatDateTime(item.reviewed_at)}
              </p>
            )}
          </div>
        )}

        {/* Actions */}
        {canReview && (
          <div className="space-y-3 border-t pt-4">
            {item.item_type === "txn_no_recording" && candidates.length > 0 && (
              <div className="space-y-1.5">
                <h3 className="text-sm font-medium">Suggested calls</h3>
                {candidates.map((c) => (
                  <div
                    key={c.instruction_id ?? c.recording_id}
                    className="flex items-center justify-between gap-2 rounded-md border px-2 py-1.5"
                  >
                    <div className="min-w-0 text-sm">
                      <span className="font-medium tabular-nums">
                        {[c.original_filename, c.side, c.quantity != null ? formatNumber(c.quantity) : null, c.stock_code]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {[c.client, c.call_started_at ? formatDateTime(c.call_started_at) : null]
                          .filter(Boolean)
                          .join(" · ")}{" "}
                        · score {formatScore(c.score)}
                      </span>
                      {c.conflicts?.map((conflict) => (
                        <span key={conflict.field} className="block text-xs text-destructive">
                          {conflict.field}: {String(conflict.transaction ?? "unknown")} vs {String(conflict.recording ?? "unknown")}
                        </span>
                      ))}
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={pending !== null}
                      onClick={() =>
                        void onManualLink(c.recording_id, c.instruction_id ?? undefined)
                      }
                    >
                      <Link2 className="mr-1 h-3.5 w-3.5" aria-hidden />
                      Link
                    </Button>
                  </div>
                ))}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="review-note">Note (optional)</Label>
              <Textarea
                id="review-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={2}
                placeholder="Why this decision…"
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                disabled={pending !== null}
                onClick={() => void onDecide("confirm")}
              >
                {pending === "confirm" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Check className="mr-2 h-4 w-4" aria-hidden />
                )}
                Confirm
              </Button>
              <Button
                size="sm"
                variant="destructive"
                disabled={pending !== null}
                onClick={() => void onDecide("reject")}
              >
                {pending === "reject" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <X className="mr-2 h-4 w-4" aria-hidden />
                )}
                Reject
              </Button>
              {item.item_type === "txn_no_recording" && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pending !== null}
                  onClick={() => setShowLink((v) => !v)}
                >
                  <Link2 className="mr-2 h-4 w-4" aria-hidden />
                  {showLink ? "Hide manual link" : "Manual link…"}
                </Button>
              )}
              {item.item_type === "recording_no_txn" && rec && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pending !== null}
                  onClick={() => setShowLinkTxn((v) => !v)}
                >
                  <Link2 className="mr-2 h-4 w-4" aria-hidden />
                  {showLinkTxn ? "Hide trade link" : "Link to a trade…"}
                </Button>
              )}
            </div>
            {showLink && item.item_type === "txn_no_recording" && (
              <div className="rounded-md border p-3">
                <p className="mb-2 text-xs text-muted-foreground">
                  Recordings from {runTradeDate} — pick the call where this order was placed.
                </p>
                <ManualLinkPicker
                  tradeDate={runTradeDate}
                  pending={pending === "link"}
                  onLink={(rid) => void onManualLink(rid)}
                />
              </div>
            )}
            {showLinkTxn && item.item_type === "recording_no_txn" && (
              <div className="rounded-md border p-3">
                <p className="mb-2 text-xs text-muted-foreground">
                  Booked trades on {runTradeDate} — pick the trade this call placed.
                </p>
                <TransactionPicker
                  tradeDate={runTradeDate}
                  pending={pending === "link"}
                  onLink={(tid) => void onLinkTransaction(tid)}
                />
              </div>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
