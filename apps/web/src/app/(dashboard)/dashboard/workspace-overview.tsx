import Link from "next/link";
import { apiJson } from "@/lib/api";

type Overview = { recordings: number; completed: number; failed: number; processing: number; risk_recordings: number; classified_calls: number; enquiries: number; amendments: number; enquiry_categories: { label: string; count: number }[] };

export async function WorkspaceOverview({ projectId, cookie }: { projectId: string; cookie: string }) {
  const data = await apiJson<Overview>("/api/workspace/overview", "get", { cookieHeader: cookie, params: { query: { project_id: projectId } } }).catch(() => null);
  if (!data) return <p role="status" className="text-sm text-muted-foreground">Unable to load overview statistics. Please refresh later.</p>;
  const metrics = [
    ["Risk recordings", data.risk_recordings, "/risks"],
    ["Enquiries", data.enquiries, null],
    ["CRS classified calls", data.classified_calls, "/recordings"],
    ["Transcript changes", data.amendments, "/amendments"],
    ["Processing", data.processing, "/recordings"],
    ["Failed", data.failed, "/recordings"],
  ] as const;
  return <section className="space-y-5 border-y py-5">
    <div className="grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-3">{metrics.map(([label, count, href]) => <div key={label}>
      <p className="text-2xl font-semibold tabular-nums">{count}</p>{href ? <Link href={href} className="text-sm text-primary hover:underline">{label}</Link> : <p className="text-sm text-muted-foreground">{label}</p>}
    </div>)}</div>
    <div className="border-t pt-4"><h2 className="mb-3 text-base font-semibold">Enquiry categories</h2>
      {data.enquiry_categories.length ? <ul className="grid gap-x-8 sm:grid-cols-2">{data.enquiry_categories.map((item) => <li key={item.label} className="flex justify-between gap-4 border-b py-2 text-sm"><span className="break-words">{item.label}</span><span className="shrink-0 tabular-nums">{item.count}</span></li>)}</ul> : <p className="text-sm text-muted-foreground">No completed CRS classifications</p>}
    </div>
  </section>;
}
