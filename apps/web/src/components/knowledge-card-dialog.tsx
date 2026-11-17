"use client";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { KnowledgeCard } from "@/lib/types";
import * as React from "react";
import { ApiError, apiJson } from "@/lib/api";
import { ArrowLeft } from "lucide-react";

export function KnowledgeCardDialog({ card, projectId, onClose }: { card: KnowledgeCard | null; projectId: string; onClose: () => void }) {
  const [faqId, setFaqId] = React.useState<string | null>(null);
  const [faq, setFaq] = React.useState<{ question: string; answer: string; source: string; demo_notice: string } | null>(null);
  const [error, setError] = React.useState("");
  React.useEffect(() => { setFaqId(null); }, [card?.id, projectId]);
  React.useEffect(() => {
    setFaq(null); setError("");
    if (!faqId || !card) return;
    const controller = new AbortController();
    apiJson<NonNullable<typeof faq>>(`/api/knowledge-faqs/${faqId}`, "get", { params: { query: { project_id: projectId } }, signal: controller.signal }).then(setFaq).catch((err: unknown) => {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError && err.status === 404 ? "This question is unavailable in the current project or has been disabled (HTTP 404)." : err instanceof ApiError && (err.status === 401 || err.status === 403) ? "Your session has expired or you do not have permission to view this question. Please sign in again." : `Unable to load the question${err instanceof ApiError ? ` (HTTP ${err.status})` : ". Please check your network connection"}.`);
    });
    return () => controller.abort();
  }, [faqId, projectId, card]);
  return (
    <Dialog open={card !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
      {card && (
        <DialogContent className="max-w-2xl" aria-labelledby="knowledge-card-title" aria-describedby="knowledge-card-notice">
          <DialogHeader>
            <span className="text-xs font-medium text-amber-800 dark:text-amber-300">{card.code} · Knowledge card</span>
            <DialogTitle id="knowledge-card-title" className="break-words text-lg">{card.title}</DialogTitle>
            <DialogDescription id="knowledge-card-notice">{card.content.demo_notice}</DialogDescription>
          </DialogHeader>
          {faqId ? <section className="space-y-4 text-sm"><button type="button" className="flex items-center gap-2 text-primary" onClick={() => setFaqId(null)}><ArrowLeft className="h-4 w-4" />Back to knowledge card</button>{error || (!faq && "Loading...")}{faq && <><h3 className="font-semibold">{faq.question}</h3><p className="whitespace-pre-wrap break-words">{faq.answer}</p><p className="text-xs text-muted-foreground">{faq.source}<br />{faq.demo_notice}</p></>}</section> : <div className="space-y-4 text-sm">
            {([
              ["Key points", card.content.key_points],
              ["Procedure / required documents", card.content.procedure],
              ["Suggested response", card.content.suggested_reply],
              ["Related products", card.content.related_products],
              ["Source", card.content.source],
            ] as const).map(([label, content]) => content && (
              <section key={label} className="space-y-1.5 border-t pt-3">
                <h3 className="font-semibold">{label}</h3>
                <p className="whitespace-pre-wrap break-words leading-relaxed">{content}</p>
              </section>
            ))}
            <section className="space-y-2 border-t pt-3"><h3 className="font-semibold">Related questions</h3>{card.related_faqs?.map((item) => <button type="button" disabled={!item.active} key={item.id} className="block text-left text-primary underline-offset-4 hover:underline disabled:opacity-50" onClick={() => setFaqId(item.id)}>{item.code} · {item.question}{!item.active && " (disabled)"}</button>)}{!card.related_faqs?.length && <p className="whitespace-pre-wrap">{card.content.related_questions || "No related questions"}</p>}</section>
            <p className="border-t pt-3 text-xs text-muted-foreground">Trigger words: {card.trigger_words.join("、")}</p>
          </div>}
        </DialogContent>
      )}
    </Dialog>
  );
}
