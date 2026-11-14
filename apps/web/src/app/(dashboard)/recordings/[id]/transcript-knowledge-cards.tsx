"use client";

import { BookOpen } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { formatMs } from "@/lib/format";
import type { KnowledgeCard, TranscriptKnowledgeCard } from "@/lib/types";

export function TranscriptKnowledgeCards({ matches, currentMs, playing, dialogOpen, onSelect, onSeek }: {
  matches: TranscriptKnowledgeCard[];
  currentMs: number;
  playing: boolean;
  dialogOpen: boolean;
  onSelect: (card: KnowledgeCard) => void;
  onSeek: (ms: number) => void;
}) {
  const [automatic, setAutomatic] = React.useState(true);
  const shown = React.useRef(new Set<string>());
  React.useEffect(() => {
    if (!playing || !automatic || dialogOpen) return;
    const active = matches.filter((match) => match.hits.some((hit) => currentMs >= hit.start_ms && currentMs <= hit.end_ms + 750));
    const next = active.find((match) => !shown.current.has(match.card.id));
    if (!next) return;
    active.forEach((match) => shown.current.add(match.card.id));
    onSelect(next.card);
  }, [automatic, currentMs, dialogOpen, matches, onSelect, playing]);

  if (matches.length === 0) return null;
  return (
    <section className="space-y-2 border-b pb-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold"><BookOpen className="h-4 w-4" aria-hidden />Knowledge cards <span className="font-normal text-muted-foreground">({matches.length})</span></h3>
        <label className="flex items-center gap-2 text-xs text-muted-foreground"><Switch checked={automatic} onCheckedChange={setAutomatic} />Auto-open on playback</label>
      </div>
      {matches.map((match) => (
        <div key={match.card.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-l-2 border-primary/40 pl-3">
          <button type="button" className="min-w-0 break-words text-left text-sm text-primary hover:underline" onClick={() => { shown.current.add(match.card.id); onSelect(match.card); }}>
            {match.card.code} · {match.card.title}
          </button>
          <Button variant="ghost" size="sm" className="h-7 text-xs tabular-nums" onClick={() => onSeek(match.hits[0].start_ms)} title="Play first trigger">{formatMs(match.hits[0].start_ms)}</Button>
          <span className="break-words text-xs text-muted-foreground">{Array.from(new Set(match.hits.flatMap((hit) => hit.matched_terms))).join("、")}</span>
        </div>
      ))}
    </section>
  );
}
