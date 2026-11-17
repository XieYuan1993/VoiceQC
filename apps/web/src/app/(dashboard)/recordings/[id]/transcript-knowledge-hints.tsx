"use client";

import { BookOpen, ChevronDown } from "lucide-react";
import type { KnowledgeCard, TranscriptKnowledgeCard } from "@/lib/types";

const colors = "border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100";

export function TranscriptKnowledgeHints({ matches, onSelect }: {
  matches: TranscriptKnowledgeCard[];
  onSelect: (card: KnowledgeCard) => void;
}) {
  if (!matches.length) return null;
  if (matches.length === 1) {
    const card = matches[0].card;
    return <button type="button" className={`inline-flex max-w-full items-start gap-2 rounded-md border px-3 py-1.5 text-left text-xs hover:brightness-95 ${colors}`} onClick={() => onSelect(card)}>
      <BookOpen className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 break-words">Knowledge card · {card.code} · {card.title}</span>
    </button>;
  }
  return <details className={`group w-full max-w-lg rounded-md border text-xs ${colors}`}>
    <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 [&::-webkit-details-marker]:hidden">
      <BookOpen className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">Knowledge hints · {matches.length} cards</span>
      <ChevronDown className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-180" aria-hidden />
    </summary>
    <div className="max-h-48 overflow-y-auto border-t border-amber-300/60 dark:border-amber-700">
      {matches.map(({ card }) => <button type="button" key={card.id} onClick={() => onSelect(card)} className="block w-full border-b border-amber-200/60 px-3 py-2 text-left last:border-b-0 hover:bg-amber-100 dark:border-amber-800 dark:hover:bg-amber-900/40">
        <span className="block break-words font-medium">{card.code} · {card.title}</span>
      </button>)}
    </div>
  </details>;
}
