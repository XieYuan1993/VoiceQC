import Link from "next/link";

import { auth } from "@/auth";
import { Pagination } from "@/components/pagination";
import { Badge, type BadgeProps } from "@/components/ui/badge";
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
import { formatDateTime } from "@/lib/format";
import { canManage } from "@/lib/roles";
import type { TxnList } from "@/lib/types";
import { cn } from "@/lib/utils";

import { cookieHeader } from "../_data";
import { TxnFilters } from "./filters";
import { TxnPanels } from "./txn-panels";

const PAGE_SIZE = 50;

const SIDE_BADGE: Record<string, BadgeProps["variant"]> = {
  buy: "success",
  sell: "destructive",
};

const CHANNEL_BADGE: Record<string, BadgeProps["variant"]> = {
  phone: "info",
  online: "neutral",
};

// Reconciliation/mapping status of a trade — its finding in the latest recon run.
const RECON_BADGE: Record<string, { variant: BadgeProps["variant"]; label: string }> = {
  matched: { variant: "success", label: "Mapped" },
  needs_review: { variant: "warning", label: "Needs review" },
  unmapped: { variant: "destructive", label: "Unmapped" },
  not_run: { variant: "neutral", label: "Not run" },
};

const RECON_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "All" },
  { value: "unmapped", label: "Unmapped" },
  { value: "needs_review", label: "Needs review" },
  { value: "matched", label: "Mapped" },
  { value: "not_run", label: "Not run" },
];

function first(v: string | string[] | undefined): string {
  return (Array.isArray(v) ? v[0] : v) ?? "";
}

function formatNumber(n: number | null): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(n);
}

export default async function TransactionsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const tradeDate = first(sp.trade_date);
  const brokerCode = first(sp.broker_code);
  const stockCode = first(sp.stock_code);
  const reconStatus = first(sp.recon_status);
  const importId = first(sp.import_id);
  const page = Math.max(1, Number(first(sp.page)) || 1);

  const session = await auth();
  const manage = canManage(session?.user?.role);

  let data: TxnList | null = null;
  let error: string | null = null;
  try {
    data = await apiCall("/api/transactions", "get", {
      cookieHeader: await cookieHeader(),
      params: {
        query: {
          trade_date: tradeDate || undefined,
          broker_code: brokerCode || undefined,
          stock_code: stockCode || undefined,
          recon_status: reconStatus || undefined,
          import_id: importId || undefined,
          page,
          page_size: PAGE_SIZE,
        },
      },
    });
  } catch (e) {
    error = getApiErrorMessage(e);
  }

  const makeHref = (p: number) => {
    const params = new URLSearchParams();
    if (tradeDate) params.set("trade_date", tradeDate);
    if (brokerCode) params.set("broker_code", brokerCode);
    if (stockCode) params.set("stock_code", stockCode);
    if (reconStatus) params.set("recon_status", reconStatus);
    if (importId) params.set("import_id", importId);
    if (p > 1) params.set("page", String(p));
    const qs = params.toString();
    return qs ? `/transactions?${qs}` : "/transactions";
  };

  const makeStatusHref = (status: string) => {
    const params = new URLSearchParams();
    if (tradeDate) params.set("trade_date", tradeDate);
    if (brokerCode) params.set("broker_code", brokerCode);
    if (stockCode) params.set("stock_code", stockCode);
    if (status) params.set("recon_status", status);
    if (importId) params.set("import_id", importId);
    const qs = params.toString();
    return qs ? `/transactions?${qs}` : "/transactions";
  };

  const hasFilters = Boolean(tradeDate || brokerCode || stockCode || reconStatus || importId);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Transactions</h1>
        <p className="text-sm text-muted-foreground">
          End-of-day trade imports matched against calls.
        </p>
      </div>

      <TxnFilters
        key={`${tradeDate}|${brokerCode}|${stockCode}`}
        tradeDate={tradeDate}
        brokerCode={brokerCode}
        stockCode={stockCode}
      />

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Mapping
        </span>
        {RECON_FILTERS.map((f) => (
          <Link
            key={f.value}
            href={makeStatusHref(f.value)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              (reconStatus || "") === f.value
                ? "border-primary bg-primary/10 text-foreground"
                : "border-transparent bg-muted/50 text-muted-foreground hover:bg-muted",
            )}
          >
            {f.label}
          </Link>
        ))}
      </div>

      {importId && (
        <div className="flex items-center justify-between rounded-md border bg-muted/40 px-4 py-2 text-sm">
          <span className="text-muted-foreground">
            Showing transactions from a single import{data ? ` · ${data.total} total` : ""}.
          </span>
          <Link href="/transactions" className="font-medium text-primary hover:underline">
            Clear ✕
          </Link>
        </div>
      )}

      {error !== null ? (
        <Card>
          <CardContent className="p-6 text-sm text-destructive">
            Failed to load transactions: {error}
          </CardContent>
        </Card>
      ) : data === null || data.items.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            No transactions
            {hasFilters ? " match these filters." : " yet — import a trade file below."}
          </CardContent>
        </Card>
      ) : (
        <>
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Ext ref</TableHead>
                  <TableHead>Ordered</TableHead>
                  <TableHead>Executed</TableHead>
                  <TableHead>Broker</TableHead>
                  <TableHead>Client</TableHead>
                  <TableHead>Stock</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead className="text-right">Quantity</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead>Channel</TableHead>
                  <TableHead>Mapping</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="whitespace-nowrap font-mono text-xs">
                      {t.ext_txn_id ?? "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {formatDateTime(t.ordered_at)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {formatDateTime(t.executed_at)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{t.broker_code ?? "—"}</TableCell>
                    <TableCell>
                      {t.client_name ?? "—"}
                      {t.client_account && (
                        <span className="block text-xs tabular-nums text-muted-foreground">
                          {t.client_account}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <span className="font-medium tabular-nums">{t.stock_code ?? "—"}</span>
                      {t.stock_name && (
                        <span className="block max-w-[160px] truncate text-xs text-muted-foreground">
                          {t.stock_name}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={SIDE_BADGE[t.side] ?? "neutral"}>{t.side}</Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(t.quantity)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(t.price)}
                    </TableCell>
                    <TableCell>
                      {t.channel ? (
                        <Badge variant={CHANNEL_BADGE[t.channel] ?? "neutral"}>{t.channel}</Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {t.recon_status ? (
                        <Badge variant={RECON_BADGE[t.recon_status]?.variant ?? "neutral"}>
                          {RECON_BADGE[t.recon_status]?.label ?? t.recon_status}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
          <Pagination
            page={data.page}
            pageSize={data.page_size}
            total={data.total}
            makeHref={makeHref}
          />
        </>
      )}

      <TxnPanels canManage={manage} />
    </div>
  );
}
