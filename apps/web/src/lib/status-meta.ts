// Single source of truth for what each status / result label means — used for
// hover tooltips and the shared StatusLegend across the app.
export type StatusMeta = { label: string; description: string };

// Reconciliation run RESULTS pills, keyed by the run.stats key.
export const RECON_RESULT_META: Record<string, StatusMeta> = {
  matched_auto: {
    label: "auto",
    description:
      "Auto-matched — a trade confidently tied to a recorded phone instruction (match score ≥ 75%, no conflicting field). No action needed.",
  },
  matched_needs_review: {
    label: "review",
    description:
      "Needs review — a match was found but it's borderline (45–75%) or a key field (quantity, price, or client) materially disagrees. Confirm before trusting it.",
  },
  txn_no_recording: {
    label: "breach",
    description:
      "Breach — a booked trade with no matching call recording: a trade with no taped instruction. The core compliance gap.",
  },
  recording_no_txn_suspicious: {
    label: "suspicious",
    description:
      "Suspicious — a call that contains a trade instruction but no booked transaction matches it (instruction given but not booked, or booked off-system).",
  },
  recording_no_txn_info: {
    label: "info",
    description:
      "Info — a call with no trade instruction and no transaction (e.g. a general enquiry). Informational only.",
  },
  decisions_carried_forward: {
    label: "carried",
    description:
      "Carried forward — confirm / reject / manual-link decisions from an earlier run of the same trade date, re-applied so a re-run keeps your review work.",
  },
};

export const RECON_RESULT_LEGEND: StatusMeta[] = Object.values(RECON_RESULT_META);

// Recon item match_status.
export const MATCH_STATUS_META: Record<string, StatusMeta> = {
  auto_matched: {
    label: "auto matched",
    description: "Matched automatically with high confidence (score ≥ 75%, no conflicting field).",
  },
  needs_review: {
    label: "needs review",
    description: "Matched but borderline, or a key field disagrees — confirm before trusting it.",
  },
  unmatched: { label: "unmatched", description: "No counterpart found above the matching threshold." },
  confirmed: { label: "confirmed", description: "A reviewer confirmed this match or finding." },
  rejected: { label: "rejected", description: "A reviewer rejected this match or finding." },
  manual_linked: {
    label: "manual linked",
    description: "A reviewer manually linked this trade to a recording.",
  },
};

// Recon item severity.
export const SEVERITY_META: Record<string, StatusMeta> = {
  breach: {
    label: "breach",
    description: "Compliance breach — a booked trade with no matching call recording.",
  },
  suspicious: {
    label: "suspicious",
    description: "A trade instruction heard on a call with no matching booked transaction.",
  },
  info: { label: "info", description: "Informational — a matched item or a non-trading call." },
};

// Recording (and recon run) processing status.
export const RECORDING_STATUS_META: Record<string, StatusMeta> = {
  uploaded: { label: "uploaded", description: "File received, waiting to be processed." },
  converting: {
    label: "converting",
    description: "Normalising the audio (format, channels, sample rate).",
  },
  transcribing: { label: "transcribing", description: "Running speech-to-text on the audio." },
  evaluating: {
    label: "evaluating",
    description: "Running the LLM evaluation against this project's criteria.",
  },
  completed: { label: "completed", description: "Processing finished successfully." },
  failed: {
    label: "failed",
    description: "Processing stopped on an error — see the failed stage.",
  },
  running: { label: "running", description: "In progress." },
  pending: { label: "pending", description: "Queued; not started yet." },
};

export const RECORDING_STATUS_LEGEND: StatusMeta[] = [
  RECORDING_STATUS_META.uploaded,
  RECORDING_STATUS_META.converting,
  RECORDING_STATUS_META.transcribing,
  RECORDING_STATUS_META.evaluating,
  RECORDING_STATUS_META.completed,
  RECORDING_STATUS_META.failed,
];

/** Tooltip text for a status label, falling back to undefined (no tooltip). */
export function describeStatus(
  meta: Record<string, StatusMeta>,
  key: string | null | undefined,
): string | undefined {
  return key ? meta[key]?.description : undefined;
}
