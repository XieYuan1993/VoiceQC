"use client";

import { History } from "lucide-react";
import type { components } from "@voiceqa/shared-types";
import { formatDateTime } from "@/lib/format";

export function TranscriptAmendmentHint({ entries }: { entries: components["schemas"]["TranscriptAmendmentOut"][] }) {
  if (!entries.length) return null;
  return <details className="max-w-2xl rounded-md border border-violet-300 bg-violet-50 px-3 py-2 text-sm text-violet-950 dark:border-violet-700 dark:bg-violet-950 dark:text-violet-100">
    <summary className="flex cursor-pointer items-center gap-2"><History className="h-4 w-4 shrink-0" /><span>Transcript edited · {entries.length} changes · {formatDateTime(entries[0].occurred_at)}</span></summary>
    <ol className="mt-2 divide-y divide-violet-200 dark:divide-violet-800">{entries.map((entry) => <li key={entry.id} className="space-y-1 py-2">
      <p className="text-xs">{formatDateTime(entry.occurred_at)} · {entry.actor ?? "—"}</p>
      <p className="whitespace-pre-wrap break-words"><span className="font-medium">Before: </span>{entry.before}</p>
      <p className="whitespace-pre-wrap break-words"><span className="font-medium">After: </span>{entry.after}</p>
    </li>)}</ol>
  </details>;
}
