import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Analytics } from "@/lib/types";
import { cn } from "@/lib/utils";

const SENTIMENT_COLOR: Record<string, string> = {
  positive: "bg-emerald-500",
  neutral: "bg-slate-400",
  mixed: "bg-amber-500",
  negative: "bg-orange-500",
  frustrated: "bg-red-500",
};

type Item = { label: string; count: number };

function BarList({ items, barClass }: { items: Item[]; barClass?: string }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">—</p>;
  }
  const max = Math.max(...items.map((i) => i.count), 1);
  return (
    <ul className="space-y-2">
      {items.map((i) => (
        <li key={i.label} className="space-y-1">
          <div className="flex items-center justify-between gap-2 text-sm">
            <span className="truncate" title={i.label}>
              {i.label}
            </span>
            <span className="shrink-0 tabular-nums text-muted-foreground">{i.count}</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              className={cn("h-full rounded-full", barClass ?? "bg-primary")}
              style={{ width: `${(i.count / max) * 100}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

function TrendChart({ trend }: { trend: Analytics["trend"] }) {
  const max = Math.max(...trend.map((t) => t.calls), 1);
  return (
    <div className="space-y-2">
      <div className="flex items-stretch gap-1">
        {trend.map((t) => (
          <div
            key={t.date}
            className="flex flex-1 flex-col items-center gap-1"
            title={`${t.date}: ${t.calls} call(s), ${t.complaints} complaint(s)${
              t.avg_sentiment != null
                ? `, avg sentiment ${t.avg_sentiment > 0 ? "+" : ""}${t.avg_sentiment.toFixed(2)}`
                : ""
            }`}
          >
            <div className="flex w-full items-end justify-center" style={{ height: 88 }}>
              <div
                className="relative w-full max-w-[24px] overflow-hidden rounded-t bg-primary/30"
                style={{ height: `${Math.max(4, (t.calls / max) * 100)}%` }}
              >
                {t.complaints > 0 && (
                  <div
                    className="absolute bottom-0 left-0 w-full bg-red-500"
                    style={{ height: `${(t.complaints / t.calls) * 100}%` }}
                  />
                )}
              </div>
            </div>
            {trend.length <= 14 && (
              <span className="text-[9px] tabular-nums text-muted-foreground">
                {t.date.slice(5)}
              </span>
            )}
          </div>
        ))}
      </div>
      {trend.length > 14 && (
        <div className="flex justify-between text-[10px] tabular-nums text-muted-foreground">
          <span>{trend[0]?.date}</span>
          <span>{trend[trend.length - 1]?.date}</span>
        </div>
      )}
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-primary/30" aria-hidden /> calls
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-red-500" aria-hidden /> complaints
        </span>
      </div>
    </div>
  );
}

export function InsightsSection({ analytics }: { analytics: Analytics }) {
  const a = analytics;
  // Only show once evaluations have produced analytics (pre-#2 runs are empty).
  const hasSignal =
    a.sentiment.length > 0 ||
    a.complaint_count > 0 ||
    a.top_topics.length > 0 ||
    a.top_intents.length > 0;
  if (!hasSignal) return null;
  const sentimentTotal = a.sentiment.reduce((s, x) => s + x.count, 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-lg font-semibold">Insights</h2>
        {a.evaluated_calls > 0 && (
          <p className="text-xs text-muted-foreground">
            Based on {a.analyzed_calls} of {a.evaluated_calls} evaluated call
            {a.evaluated_calls === 1 ? "" : "s"}
          </p>
        )}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Customer sentiment */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Customer sentiment</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {a.avg_sentiment != null && (
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-semibold tabular-nums">
                  {a.avg_sentiment > 0 ? "+" : ""}
                  {a.avg_sentiment.toFixed(2)}
                </span>
                <span className="text-xs text-muted-foreground">avg (&minus;1…+1)</span>
              </div>
            )}
            {sentimentTotal > 0 && (
              <div className="flex h-2.5 w-full overflow-hidden rounded-full">
                {a.sentiment.map((s) => (
                  <div
                    key={s.label}
                    className={cn(SENTIMENT_COLOR[s.label] ?? "bg-muted")}
                    style={{ width: `${(s.count / sentimentTotal) * 100}%` }}
                    title={`${s.label}: ${s.count}`}
                  />
                ))}
              </div>
            )}
            <ul className="space-y-1 text-sm">
              {a.sentiment.map((s) => (
                <li key={s.label} className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5">
                    <span
                      className={cn(
                        "h-2 w-2 rounded-full",
                        SENTIMENT_COLOR[s.label] ?? "bg-muted",
                      )}
                      aria-hidden
                    />
                    <span className="capitalize">{s.label}</span>
                  </span>
                  <span className="tabular-nums text-muted-foreground">{s.count}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        {/* Complaints */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Complaints</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-semibold tabular-nums">
                {Math.round(a.complaint_rate * 100)}%
              </span>
              <span className="text-xs text-muted-foreground">
                {a.complaint_count} of {a.analyzed_calls} calls
              </span>
            </div>
            <div>
              <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                Top categories
              </p>
              <BarList items={a.complaint_categories} barClass="bg-red-500" />
            </div>
          </CardContent>
        </Card>

        {/* Top call reasons (intents) */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Top call reasons</CardTitle>
          </CardHeader>
          <CardContent>
            <BarList items={a.top_intents} barClass="bg-sky-500" />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {a.top_topics.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Top topics</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {a.top_topics.map((t) => (
                  <Badge key={t.label} variant="neutral" className="font-normal">
                    {t.label}
                    <span className="ml-1.5 tabular-nums opacity-70">{t.count}</span>
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {a.trend.length > 1 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Daily trend</CardTitle>
            </CardHeader>
            <CardContent>
              <TrendChart trend={a.trend} />
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
