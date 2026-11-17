"use client";

import * as React from "react";
import { BookOpen, Pencil, Plus, Upload } from "lucide-react";
import type { components } from "@voiceqa/shared-types";
import { apiJson, uploadMultipart } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { KnowledgeCardDialog } from "@/components/knowledge-card-dialog";
import type { KnowledgeCard } from "@/lib/types";

type Faq = components["schemas"]["KnowledgeFaqOut"];
type CardInput = components["schemas"]["KnowledgeCardIn"];
type FaqInput = components["schemas"]["KnowledgeFaqIn"];
const contentFields = { key_points: "Key points", procedure: "Procedure / required documents", suggested_reply: "Suggested response", related_products: "Related products", source: "Source", demo_notice: "Data notice" } as const;
const blankCard = (): CardInput => ({ code: "", title: "", trigger_words: [], active: true, content: { key_points: "", procedure: "", suggested_reply: "", related_products: "", related_questions: "", source: "", demo_notice: "Demo content, not verified by FWD", related_faq_codes: [] } });
const blankFaq = (): FaqInput => ({ code: "", category: "", question: "", answer: "", source: "", demo_notice: "Demo content, not verified by FWD", active: true });
const inputClass = "w-full rounded-md border bg-background px-3 py-2 text-sm";

export function KnowledgeManager({ projectId, canManage }: { projectId: string; canManage: boolean }) {
  const [cards, setCards] = React.useState<KnowledgeCard[]>([]);
  const [faqs, setFaqs] = React.useState<Faq[]>([]);
  const [tab, setTab] = React.useState<"cards" | "faqs">("cards");
  const [search, setSearch] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [loaded, setLoaded] = React.useState(false);
  const [notice, setNotice] = React.useState("");
  const [selected, setSelected] = React.useState<KnowledgeCard | null>(null);
  const [editing, setEditing] = React.useState<{ kind: "cards" | "faqs"; id?: string } | null>(null);
  const [card, setCard] = React.useState<CardInput>(blankCard);
  const [faq, setFaq] = React.useState<FaqInput>(blankFaq);
  const [triggers, setTriggers] = React.useState("");
  const load = React.useCallback(async () => {
    const query = { project_id: projectId, include_inactive: true };
    const [nextCards, nextFaqs] = await Promise.all([
      apiJson<KnowledgeCard[]>("/api/knowledge-cards", "get", { params: { query } }),
      apiJson<Faq[]>("/api/knowledge-faqs", "get", { params: { query } }),
    ]);
    setCards(nextCards); setFaqs(nextFaqs); setLoaded(true);
  }, [projectId]);
  React.useEffect(() => { let active = true; load().catch(() => { if (active) setError("Unable to load the knowledge base."); }); return () => { active = false; }; }, [load]);
  function editCard(value?: KnowledgeCard) { setCard(value ?? blankCard()); setTriggers(value?.trigger_words.join("\n") ?? ""); setError(""); setEditing({ kind: "cards", id: value?.id }); }
  function editFaq(value?: Faq) { setFaq(value ?? blankFaq()); setError(""); setEditing({ kind: "faqs", id: value?.id }); }
  async function save(event: React.FormEvent) {
    event.preventDefault(); if (!editing) return;
    setBusy(true); setError("");
    try {
      const payload = editing.kind === "cards" ? { ...card, trigger_words: triggers.split(/[\n、,，]/).map((word) => word.trim()).filter(Boolean) } : faq;
      const path = editing.kind === "cards" ? "/api/knowledge-cards" : "/api/knowledge-faqs";
      await apiJson(path + (editing.id ? `/${editing.id}` : ""), editing.id ? "put" : "post", { params: { query: { project_id: projectId } }, body: payload });
      await load(); setEditing(null); setNotice("Saved.");
    } catch { setError("Unable to save. Check required fields, duplicate codes and related questions."); }
    finally { setBusy(false); }
  }
  async function importWorkbook(file: File) {
    setBusy(true); setError("");
    try {
      const result = await uploadMultipart<{ created: number; updated: number; faqs_created: number; faqs_updated: number }>("/api/knowledge-cards/import", file, { query: { project_id: projectId } });
      await load(); setNotice(`Cards: ${result.created} added, ${result.updated} updated. FAQs: ${result.faqs_created} added, ${result.faqs_updated} updated.`);
    } catch { setError("Unable to import. Use an XLSX workbook containing the knowledge cards and FAQs sheets."); }
    finally { setBusy(false); }
  }
  const term = search.trim().toLocaleLowerCase();
  return <div className="space-y-5">
    <header className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-2xl font-semibold">Knowledge base</h1>{canManage && <div className="flex gap-2"><label className="inline-flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm"><Upload className="h-4 w-4" />Import Excel<input type="file" accept=".xlsx" className="sr-only" disabled={busy} onChange={(e) => { const file = e.target.files?.[0]; if (file) void importWorkbook(file); e.target.value = ""; }} /></label><Button disabled={busy} onClick={() => tab === "cards" ? editCard() : editFaq()}><Plus className="mr-2 h-4 w-4" />Add</Button></div>}</header>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm text-primary">{notice}</p>}
    <div className="flex flex-wrap items-center gap-4 border-b pb-3"><div role="tablist" className="flex gap-2">{(["cards", "faqs"] as const).map((value) => <button key={value} role="tab" aria-selected={tab === value} onClick={() => setTab(value)} className={`border-b-2 px-3 py-2 text-sm ${tab === value ? "border-primary text-primary" : "border-transparent"}`}>{value === "cards" ? `Knowledge card (${cards.length})` : `FAQ (${faqs.length})`}</button>)}</div><input aria-label="Search knowledge base" placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} className={`${inputClass} max-w-sm`} /></div>
    {!loaded && !error && <p className="text-sm text-muted-foreground">Loading...</p>}
    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b text-muted-foreground"><th className="p-3">Code</th><th className="p-3">{tab === "cards" ? "Title / trigger words" : "Question / category"}</th><th className="p-3">Status</th><th className="p-3 text-right">Actions</th></tr></thead><tbody>
      {tab === "cards" ? cards.filter((item) => `${item.code} ${item.title} ${item.trigger_words.join(" ")}`.toLowerCase().includes(term)).map((item) => <tr key={item.id} className="border-b"><td className="p-3">{item.code}</td><td className="max-w-lg p-3"><div className="break-words font-medium">{item.title}</div><div className="mt-1 break-words text-xs text-muted-foreground">{item.trigger_words.join("、")}</div></td><td className="p-3">{item.active ? "Active" : "Inactive"}</td><td className="whitespace-nowrap p-3 text-right"><Button size="icon" variant="ghost" title="View card" aria-label="View card" onClick={() => setSelected(item)}><BookOpen className="h-4 w-4" /></Button>{canManage && <Button size="icon" variant="ghost" title="Edit card" aria-label="Edit card" onClick={() => editCard(item)}><Pencil className="h-4 w-4" /></Button>}</td></tr>) : faqs.filter((item) => `${item.code} ${item.question} ${item.answer} ${item.category}`.toLowerCase().includes(term)).map((item) => <tr key={item.id} className="border-b"><td className="p-3">{item.code}</td><td className="max-w-lg p-3"><div className="break-words font-medium">{item.question}</div><div className="mt-1 text-xs text-muted-foreground">{item.category}</div>{!canManage && <p className="mt-2 whitespace-pre-wrap break-words">{item.answer}</p>}</td><td className="p-3">{item.active ? "Active" : "Inactive"}</td><td className="p-3 text-right">{canManage && <Button size="icon" variant="ghost" title="Edit question" aria-label="Edit question" onClick={() => editFaq(item)}><Pencil className="h-4 w-4" /></Button>}</td></tr>)}
    </tbody></table>{loaded && (tab === "cards" ? cards : faqs).length === 0 && <p className="p-4 text-sm text-muted-foreground">No records</p>}</div>
    <KnowledgeCardDialog projectId={projectId} card={selected} onClose={() => setSelected(null)} />
    <Dialog open={!!editing} onOpenChange={(open) => { if (!open && !busy) setEditing(null); }}><DialogContent className="max-w-2xl"><DialogHeader><DialogTitle>{editing?.id ? "Edit " : "Add "}{editing?.kind === "cards" ? "knowledge card" : "FAQ"}</DialogTitle></DialogHeader><form onSubmit={save} className="space-y-4">
      {editing?.kind === "cards" ? <>
        <label className="block space-y-1 text-sm"><span>Code</span><input className={inputClass} required pattern="K[0-9]{2,4}" placeholder="K20" disabled={!!editing.id} value={card.code} onChange={(e) => setCard({ ...card, code: e.target.value.toUpperCase() })} /></label>
        <label className="block space-y-1 text-sm"><span>Title</span><input className={inputClass} required value={card.title} onChange={(e) => setCard({ ...card, title: e.target.value })} /></label>
        <label className="block space-y-1 text-sm"><span>Trigger words (one per line)</span><textarea className={inputClass} required rows={3} value={triggers} onChange={(e) => setTriggers(e.target.value)} /></label>
        {Object.entries(contentFields).map(([key, label]) => <label key={key} className="block space-y-1 text-sm"><span>{label}</span><textarea className={inputClass} rows={3} value={String(card.content[key as keyof typeof contentFields] ?? "")} onChange={(e) => setCard({ ...card, content: { ...card.content, [key]: e.target.value } })} /></label>)}
        <fieldset className="space-y-2"><legend className="mb-2 text-sm font-medium">Related questions</legend><div className="max-h-48 space-y-2 overflow-y-auto border p-3">{faqs.map((item) => <label key={item.id} className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={card.content.related_faq_codes?.includes(item.code) ?? false} onChange={(e) => setCard({ ...card, content: { ...card.content, related_faq_codes: e.target.checked ? [...(card.content.related_faq_codes ?? []), item.code] : card.content.related_faq_codes?.filter((code) => code !== item.code) } })} /><span>{item.code} · {item.question}{!item.active && " (disabled)"}</span></label>)}</div></fieldset>
      </> : <>
        {(["code", "category", "question", "answer", "source", "demo_notice"] as const).map((key) => <label key={key} className="block space-y-1 text-sm"><span>{{ code: "Code", category: "Category", question: "Question", answer: "Answer", source: "Source", demo_notice: "Data notice" }[key]}</span>{key === "answer" ? <textarea className={inputClass} required rows={8} value={faq[key]} onChange={(e) => setFaq({ ...faq, [key]: e.target.value })} /> : <input className={inputClass} required={key === "code" || key === "question"} disabled={key === "code" && !!editing?.id} pattern={key === "code" ? "F[0-9]{2,4}" : undefined} value={faq[key] ?? ""} onChange={(e) => setFaq({ ...faq, [key]: key === "code" ? e.target.value.toUpperCase() : e.target.value })} />}</label>)}
      </>}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={(editing?.kind === "cards" ? card.active : faq.active) ?? true} onChange={(e) => editing?.kind === "cards" ? setCard({ ...card, active: e.target.checked }) : setFaq({ ...faq, active: e.target.checked })} />Active</label>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}<div className="flex justify-end gap-2"><Button type="button" variant="outline" disabled={busy} onClick={() => setEditing(null)}>Cancel</Button><Button type="submit" disabled={busy}>{busy ? "Saving..." : "Save"}</Button></div>
    </form></DialogContent></Dialog>
  </div>;
}
