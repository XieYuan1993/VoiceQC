"use client";

import { BookOpen, Loader2, Upload } from "lucide-react";
import * as React from "react";

import { KnowledgeCardDialog } from "@/components/knowledge-card-dialog";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiCall, getApiErrorMessage, uploadMultipart } from "@/lib/api";
import type { KnowledgeCard } from "@/lib/types";

export function KnowledgeCardsSection({ projectId, canManage }: { projectId: string; canManage: boolean }) {
  const [cards, setCards] = React.useState<KnowledgeCard[] | null>(null);
  const [selected, setSelected] = React.useState<KnowledgeCard | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [importing, setImporting] = React.useState(false);
  const input = React.useRef<HTMLInputElement>(null);

  const load = React.useCallback(async () => {
    try {
      setCards(await apiCall("/api/knowledge-cards", "get", { params: { query: { project_id: projectId } } }));
      setError(null);
    } catch (err) { setError(getApiErrorMessage(err)); }
  }, [projectId]);

  React.useEffect(() => { void load(); }, [load]);

  async function onImport(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setImporting(true); setNotice(null); setError(null);
    try {
      const result = await uploadMultipart<{ created: number; updated: number; total: number }>(
        "/api/knowledge-cards/import", file, { query: { project_id: projectId } },
      );
      setNotice(`${result.total} cards imported: ${result.created} created, ${result.updated} updated.`);
      await load();
    } catch (err) { setError(getApiErrorMessage(err)); }
    finally { setImporting(false); }
  }

  return (
    <section className="space-y-3 border-t pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-base font-semibold"><BookOpen className="h-4 w-4" aria-hidden />Knowledge cards {cards && <span className="text-sm font-normal text-muted-foreground">({cards.length})</span>}</h2>
        {canManage && <>
          <input ref={input} type="file" accept=".xlsx" className="hidden" onChange={(event) => void onImport(event)} />
          <Button variant="outline" size="sm" disabled={importing} onClick={() => input.current?.click()}>
            {importing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : <Upload className="mr-2 h-4 w-4" aria-hidden />}Import workbook
          </Button>
        </>}
      </div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {notice && <p role="status" className="text-sm text-primary">{notice}</p>}
      {!cards && !error && <Loader2 className="h-4 w-4 animate-spin" aria-label="Loading knowledge cards" />}
      {cards?.length === 0 && <p className="text-sm text-muted-foreground">No knowledge cards.</p>}
      {cards && cards.length > 0 && <Table>
        <TableHeader><TableRow><TableHead>Code</TableHead><TableHead>Title</TableHead><TableHead>Triggers</TableHead><TableHead className="text-right">View</TableHead></TableRow></TableHeader>
        <TableBody>{cards.map((card) => <TableRow key={card.id}>
          <TableCell className="whitespace-nowrap text-xs font-medium">{card.code}</TableCell>
          <TableCell className="min-w-40 break-words">{card.title}</TableCell>
          <TableCell className="max-w-sm whitespace-normal break-words text-xs text-muted-foreground">{card.trigger_words.join("、")}</TableCell>
          <TableCell className="text-right"><Button variant="ghost" size="icon" aria-label={`View ${card.code}`} title={`View ${card.code}`} onClick={() => setSelected(card)}><BookOpen className="h-4 w-4" aria-hidden /></Button></TableCell>
        </TableRow>)}</TableBody>
      </Table>}
      <KnowledgeCardDialog card={selected} onClose={() => setSelected(null)} />
    </section>
  );
}
