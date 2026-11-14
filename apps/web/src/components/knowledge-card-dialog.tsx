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
      setError(err instanceof ApiError && err.status === 404 ? "此問題不存在於目前專案，或已停用（HTTP 404）。" : err instanceof ApiError && (err.status === 401 || err.status === 403) ? "登入已失效或沒有讀取此問題的權限，請重新登入。" : `無法載入問題${err instanceof ApiError ? `（HTTP ${err.status}）` : "，請檢查網絡連線"}。`);
    });
    return () => controller.abort();
  }, [faqId, projectId, card]);
  return (
    <Dialog open={card !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
      {card && (
        <DialogContent className="max-w-2xl" aria-labelledby="knowledge-card-title" aria-describedby="knowledge-card-notice">
          <DialogHeader>
            <span className="text-xs font-medium text-primary">{card.code} · Knowledge card</span>
            <DialogTitle id="knowledge-card-title" className="break-words text-lg">{card.title}</DialogTitle>
            <DialogDescription id="knowledge-card-notice">{card.content.demo_notice}</DialogDescription>
          </DialogHeader>
          {faqId ? <section className="space-y-4 text-sm"><button type="button" className="flex items-center gap-2 text-primary" onClick={() => setFaqId(null)}><ArrowLeft className="h-4 w-4" />返回知識卡片</button>{error || (!faq && "載入中…")}{faq && <><h3 className="font-semibold">{faq.question}</h3><p className="whitespace-pre-wrap break-words">{faq.answer}</p><p className="text-xs text-muted-foreground">{faq.source}<br />{faq.demo_notice}</p></>}</section> : <div className="space-y-4 text-sm">
            {([
              ["要點", card.content.key_points],
              ["辦理步驟／所需文件", card.content.procedure],
              ["建議回覆", card.content.suggested_reply],
              ["相關產品", card.content.related_products],
              ["出處", card.content.source],
            ] as const).map(([label, content]) => content && (
              <section key={label} className="space-y-1.5 border-t pt-3">
                <h3 className="font-semibold">{label}</h3>
                <p className="whitespace-pre-wrap break-words leading-relaxed">{content}</p>
              </section>
            ))}
            <section className="space-y-2 border-t pt-3"><h3 className="font-semibold">相關問題</h3>{card.related_faqs?.map((item) => <button type="button" disabled={!item.active} key={item.id} className="block text-left text-primary underline-offset-4 hover:underline disabled:opacity-50" onClick={() => setFaqId(item.id)}>{item.code} · {item.question}{!item.active && "（已停用）"}</button>)}{!card.related_faqs?.length && <p className="whitespace-pre-wrap">{card.content.related_questions || "暫無相關問題"}</p>}</section>
            <p className="border-t pt-3 text-xs text-muted-foreground">觸發詞：{card.trigger_words.join("、")}</p>
          </div>}
        </DialogContent>
      )}
    </Dialog>
  );
}
