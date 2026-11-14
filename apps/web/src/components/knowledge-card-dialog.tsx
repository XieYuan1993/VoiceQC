"use client";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { KnowledgeCard } from "@/lib/types";

export function KnowledgeCardDialog({ card, onClose }: { card: KnowledgeCard | null; onClose: () => void }) {
  return (
    <Dialog open={card !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
      {card && (
        <DialogContent className="max-w-2xl" aria-labelledby="knowledge-card-title" aria-describedby="knowledge-card-notice">
          <DialogHeader>
            <span className="text-xs font-medium text-primary">{card.code} · Knowledge card</span>
            <DialogTitle id="knowledge-card-title" className="break-words text-lg">{card.title}</DialogTitle>
            <DialogDescription id="knowledge-card-notice">{card.content.demo_notice}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 text-sm">
            {([
              ["要點", card.content.key_points],
              ["辦理步驟／所需文件", card.content.procedure],
              ["建議回覆", card.content.suggested_reply],
              ["相關產品", card.content.related_products],
              ["相關問題", card.content.related_questions],
              ["出處", card.content.source],
            ] as const).map(([label, content]) => content && (
              <section key={label} className="space-y-1.5 border-t pt-3">
                <h3 className="font-semibold">{label}</h3>
                <p className="whitespace-pre-wrap break-words leading-relaxed">{content}</p>
              </section>
            ))}
            <p className="border-t pt-3 text-xs text-muted-foreground">觸發詞：{card.trigger_words.join("、")}</p>
          </div>
        </DialogContent>
      )}
    </Dialog>
  );
}
