import { AudioLines, BookCheck, ClipboardCheck, Layers, ListChecks, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiCall } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { getActiveProject } from "@/lib/project";
import type { Analytics, BatchList, RecordingList } from "@/lib/types";

import { cookieHeader } from "../_data";
import { InsightsSection } from "./insights-section";

function MetricCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  icon: typeof AudioLines;
}) {
  return (
    <Card className="bg-muted/40">
      <CardContent className="flex items-center gap-4 p-5">
        <span
          aria-hidden
          className="inline-flex h-10 w-10 items-center justify-center rounded-md bg-secondary text-secondary-foreground"
        >
          <Icon className="h-5 w-5" />
        </span>
        <div>
          <p className="text-2xl font-semibold tabular-nums leading-none">{value}</p>
          <p className="mt-1 text-sm text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export default async function DashboardHomePage() {
  const cookie = await cookieHeader();
  const { id: projectId, project } = await getActiveProject(cookie);
  const projectQuery = projectId || undefined;

  // Each read is independent and resilient: a failure shows a dash rather than
  // breaking the whole overview.
  const [recordings, completed, batches, recent, analytics] = await Promise.all([
    apiCall("/api/recordings", "get", {
      cookieHeader: cookie,
      params: { query: { project_id: projectQuery, page_size: 1 } },
    }).catch(() => null as RecordingList | null),
    apiCall("/api/recordings", "get", {
      cookieHeader: cookie,
      params: { query: { project_id: projectQuery, status: "completed", page_size: 1 } },
    }).catch(() => null as RecordingList | null),
    apiCall("/api/batches", "get", {
      cookieHeader: cookie,
      params: { query: { project_id: projectQuery, page_size: 1 } },
    }).catch(() => null as BatchList | null),
    apiCall("/api/recordings", "get", {
      cookieHeader: cookie,
      params: { query: { project_id: projectQuery, page_size: 6 } },
    }).catch(() => null as RecordingList | null),
    apiCall("/api/insights/analytics", "get", {
      cookieHeader: cookie,
      params: { query: { project_id: projectQuery } },
    }).catch(() => null as Analytics | null),
  ]);

  const recentItems = recent?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{project?.name ?? "Dashboard"}</h1>
        <p className="text-sm text-muted-foreground">Call quality &amp; compliance</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <MetricCard
          label="Recordings"
          value={recordings ? recordings.total : "—"}
          icon={AudioLines}
        />
        <MetricCard label="Evaluated" value={completed ? completed.total : "—"} icon={ListChecks} />
        <MetricCard label="Batches" value={batches ? batches.total : "—"} icon={Layers} />
      </div>

      {analytics && analytics.analyzed_calls > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <MetricCard
            label="Avg script adherence"
            value={
              analytics.avg_adherence != null ? `${Math.round(analytics.avg_adherence)}%` : "—"
            }
            icon={ClipboardCheck}
          />
          <MetricCard
            label="Avg answer accuracy"
            value={
              analytics.avg_correctness != null ? `${Math.round(analytics.avg_correctness)}%` : "—"
            }
            icon={BookCheck}
          />
          <MetricCard
            label="Calls with wrong answers"
            value={analytics.incorrect_answer_calls}
            icon={TriangleAlert}
          />
        </div>
      )}

      {analytics && <InsightsSection analytics={analytics} />}

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">Recent calls</CardTitle>
          <Link href="/recordings" className="text-sm font-medium text-primary hover:underline">
            View all
          </Link>
        </CardHeader>
        <CardContent>
          {recentItems.length === 0 ? (
            <div className="rounded-md border border-dashed p-8 text-center">
              <p className="text-sm text-muted-foreground">
                No calls yet for this project.
              </p>
              <Link
                href="/batches"
                className="mt-2 inline-block text-sm font-medium text-primary hover:underline"
              >
                Create a batch to upload recordings
              </Link>
            </div>
          ) : (
            <ul className="divide-y">
              {recentItems.map((r) => (
                <li key={r.id}>
                  <Link
                    href={`/recordings/${r.id}`}
                    className="flex items-center gap-3 py-2.5 transition-colors hover:bg-muted/40"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium" title={r.original_filename}>
                        {r.original_filename}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {r.broker_ext ? `Agent ${r.broker_ext}` : "Agent —"}
                        {r.client_name ? ` · ${r.client_name}` : ""}
                        {r.call_started_at ? ` · ${formatDateTime(r.call_started_at)}` : ""}
                      </p>
                    </div>
                    <StatusBadge status={r.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
