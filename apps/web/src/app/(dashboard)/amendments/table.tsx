"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Search } from "lucide-react";
import { apiJson, getApiErrorMessage } from "@/lib/api";
import { formatDateTime, formatMs } from "@/lib/format";
import { Button } from "@/components/ui/button";

type Entry = { id: number; recording_id: string; filename: string; occurred_at: string; actor: string | null; segment_id: string; start_ms: number | null; before: string; after: string };
type Result = { total: number; items: Entry[]; page_size: number };

export function AmendmentTable({ projectId }: { projectId: string }) {
  const [page, setPage] = React.useState(1);
  const [query, setQuery] = React.useState("");
  const [draft, setDraft] = React.useState("");
  const [data, setData] = React.useState<Result | null>(null);
  const [error, setError] = React.useState("");
  const [refresh, setRefresh] = React.useState(0);
  React.useEffect(() => {
    let active = true; setData(null); setError("");
    apiJson<Result>("/api/workspace/amendments", "get", { params: { query: { project_id: projectId, page, q: query } } })
      .then((value) => { if (active) setData(value); }).catch((e) => { if (active) setError(getApiErrorMessage(e)); });
    return () => { active = false; };
  }, [projectId, page, query, refresh]);
  return <div className="space-y-5">
    <h1 className="text-2xl font-semibold">Transcript changes</h1>
    <form className="flex max-w-lg gap-2" onSubmit={(e) => { e.preventDefault(); setPage(1); setQuery(draft.trim()); }}>
      <input aria-label="Search recording filename" placeholder="Search recording filename" value={draft} onChange={(e) => setDraft(e.target.value)} className="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 text-sm" />
      <Button type="submit" size="icon" title="Search" aria-label="Search"><Search className="h-4 w-4" /></Button>
    </form>
    {error ? <div role="alert" className="space-y-2 text-destructive"><p>{error}</p><Button variant="outline" onClick={() => setRefresh((n) => n + 1)}>Retry</Button></div>
      : !data ? <p role="status">Loading...</p> : <>
        <div className="overflow-x-auto"><table className="w-full min-w-[800px] table-fixed text-left text-sm"><thead><tr className="border-b text-muted-foreground"><th className="w-44 p-3">Time / edited by</th><th className="w-52 p-3">Recording / segment</th><th className="p-3">Before</th><th className="p-3">After</th></tr></thead>
          <tbody>{data.items.map((entry) => <tr key={entry.id} className="border-b align-top"><td className="break-words p-3">{formatDateTime(entry.occurred_at)}<div className="mt-1 text-xs text-muted-foreground">{entry.actor ?? "—"}</div></td>
            <td className="break-words p-3"><Link className="text-primary hover:underline" href={`/recordings/${entry.recording_id}`}>{entry.filename}</Link><div className="mt-1 text-xs text-muted-foreground">{entry.start_ms != null ? formatMs(entry.start_ms) : `#${entry.segment_id}`}</div></td>
            <td className="whitespace-pre-wrap break-words p-3">{entry.before}</td><td className="whitespace-pre-wrap break-words p-3">{entry.after}</td></tr>)}</tbody></table>
          {!data.items.length && <p className="py-8 text-center text-sm text-muted-foreground">No transcript changes</p>}</div>
        <div className="flex items-center justify-between gap-3 text-sm"><span>{data.total} records · Page {page}</span><div className="flex gap-2"><Button size="icon" variant="outline" title="Previous page" aria-label="Previous page" disabled={page === 1} onClick={() => setPage(page - 1)}><ArrowLeft className="h-4 w-4" /></Button><Button size="icon" variant="outline" title="Next page" aria-label="Next page" disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}><ArrowRight className="h-4 w-4" /></Button></div></div>
      </>}
  </div>;
}
