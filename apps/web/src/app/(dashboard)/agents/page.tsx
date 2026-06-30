import { ChevronRight } from "lucide-react";
import Link from "next/link";

import { LinkedRow } from "@/components/linked-row";
import { MetricBar } from "@/components/metric-bar";
import { Sparkline } from "@/components/sparkline";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiCall, getApiErrorMessage } from "@/lib/api";
import { getActiveProject } from "@/lib/project";
import { scoreBgClass, scoreTextClass } from "@/lib/score";
import type { AgentScorecards } from "@/lib/types";
import { cn } from "@/lib/utils";

import { cookieHeader } from "../_data";

function SummaryCard({
  label,
  value,
  tone,
  href,
}: {
  label: string;
  value: string | number;
  tone?: string;
  href?: string;
}) {
  const body = (
    <CardContent className="p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("mt-1 text-2xl font-semibold tabular-nums", tone)}>{value}</p>
    </CardContent>
  );
  if (href) {
    return (
      <Card className="transition-colors hover:bg-muted/40">
        <Link href={href as never} className="block">
          {body}
        </Link>
      </Card>
    );
  }
  return <Card>{body}</Card>;
}

export default async function AgentsPage() {
  const cookie = await cookieHeader();
  const { id: projectId } = await getActiveProject(cookie);

  let data: AgentScorecards | null = null;
  let error: string | null = null;
  try {
    data = await apiCall("/api/insights/agents", "get", {
      cookieHeader: cookie,
      params: { query: { project_id: projectId || undefined } },
    });
  } catch (e) {
    error = getApiErrorMessage(e);
  }

  const agents = data?.agents ?? [];
  const summary = data?.summary;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Agent scorecards</h1>
        <p className="text-sm text-muted-foreground">
          Per-agent QA &amp; compliance rollup from each call&apos;s latest evaluation — lowest
          average score first. Select an agent to drill into their calls.
        </p>
      </div>

      {error !== null ? (
        <Card>
          <CardContent className="p-6 text-sm text-destructive">
            Failed to load agent scorecards: {error}
          </CardContent>
        </Card>
      ) : agents.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            No evaluated calls yet for this project.
          </CardContent>
        </Card>
      ) : (
        <>
          {summary && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <SummaryCard label="Agents" value={summary.agents} />
              <SummaryCard label="Calls evaluated" value={summary.calls} />
              <SummaryCard
                label="Team avg score"
                value={summary.team_avg_score != null ? Math.round(summary.team_avg_score) : "—"}
                tone={scoreTextClass(summary.team_avg_score)}
              />
              <SummaryCard
                label="In review queue"
                value={summary.in_review_queue}
                tone={summary.in_review_queue > 0 ? "text-red-600 dark:text-red-400" : undefined}
                href="/review"
              />
            </div>
          )}

          <Card>
            <CardContent className="space-y-3 p-5">
              <h2 className="text-sm font-medium text-muted-foreground">Average score by agent</h2>
              <div className="space-y-2">
                {agents.map((ag) => (
                  <div key={ag.agent} className="flex items-center gap-3">
                    <span className="w-12 shrink-0 text-sm tabular-nums text-muted-foreground">
                      {ag.agent}
                    </span>
                    <div className="h-4 flex-1 overflow-hidden rounded bg-muted">
                      <div
                        className={cn("h-full rounded", scoreBgClass(ag.avg_score))}
                        style={{ width: `${ag.avg_score ?? 0}%` }}
                      />
                    </div>
                    <span
                      className={cn(
                        "w-8 shrink-0 text-right text-sm font-medium tabular-nums",
                        scoreTextClass(ag.avg_score),
                      )}
                    >
                      {ag.avg_score != null ? Math.round(ag.avg_score) : "—"}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Agent</TableHead>
                  <TableHead className="text-right">Calls</TableHead>
                  <TableHead className="text-right">Avg score</TableHead>
                  <TableHead className="text-right">Adherence</TableHead>
                  <TableHead className="text-right">Accuracy</TableHead>
                  <TableHead>30-day trend</TableHead>
                  <TableHead className="text-right">Complaints</TableHead>
                  <TableHead className="text-right">Wrong</TableHead>
                  <TableHead className="w-8" aria-label="Open" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {agents.map((ag) => (
                  <LinkedRow key={ag.agent} href={`/agents/${encodeURIComponent(ag.agent)}`}>
                    <TableCell className="font-medium tabular-nums">{ag.agent}</TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {ag.calls}
                    </TableCell>
                    <TableCell>
                      <MetricBar value={ag.avg_score} className="ml-auto" />
                    </TableCell>
                    <TableCell>
                      <MetricBar value={ag.avg_adherence} suffix="%" className="ml-auto" />
                    </TableCell>
                    <TableCell>
                      <MetricBar value={ag.avg_correctness} suffix="%" className="ml-auto" />
                    </TableCell>
                    <TableCell>
                      <Sparkline values={(ag.trend ?? []).map((t) => t.avg_score)} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {Math.round(ag.complaint_rate * 100)}%
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums",
                        ag.incorrect_answer_calls > 0
                          ? "font-medium text-red-600 dark:text-red-400"
                          : "text-muted-foreground",
                      )}
                    >
                      {ag.incorrect_answer_calls}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      <ChevronRight aria-hidden className="h-4 w-4" />
                    </TableCell>
                  </LinkedRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        </>
      )}
    </div>
  );
}
