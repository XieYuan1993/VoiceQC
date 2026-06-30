"use client";

import { X } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// Filter state lives in the URL; the server page refetches on change. The
// parent keys this component on the params so internal state resets when the
// URL changes from elsewhere (same pattern as recordings/filters.tsx).
export function TxnFilters({
  tradeDate,
  brokerCode,
  stockCode,
}: {
  tradeDate: string;
  brokerCode: string;
  stockCode: string;
}) {
  const router = useRouter();
  const [broker, setBroker] = React.useState(brokerCode);
  const [stock, setStock] = React.useState(stockCode);

  function apply(next: Partial<{ trade_date: string; broker_code: string; stock_code: string }>) {
    const merged = {
      trade_date: tradeDate,
      broker_code: broker.trim(),
      stock_code: stock.trim(),
      ...next,
    };
    const params = new URLSearchParams();
    if (merged.trade_date) params.set("trade_date", merged.trade_date);
    if (merged.broker_code) params.set("broker_code", merged.broker_code);
    if (merged.stock_code) params.set("stock_code", merged.stock_code);
    const qs = params.toString();
    router.replace(qs ? `/transactions?${qs}` : "/transactions");
  }

  const hasFilters = Boolean(tradeDate || brokerCode || stockCode);

  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        apply({});
      }}
    >
      <Input
        type="date"
        value={tradeDate}
        onChange={(e) => apply({ trade_date: e.target.value })}
        className="w-44"
        aria-label="Filter by trade date"
      />
      <Input
        value={broker}
        onChange={(e) => setBroker(e.target.value)}
        onBlur={() => broker.trim() !== brokerCode && apply({})}
        placeholder="Broker code"
        className="w-36"
        aria-label="Filter by broker code"
      />
      <Input
        value={stock}
        onChange={(e) => setStock(e.target.value)}
        onBlur={() => stock.trim() !== stockCode && apply({})}
        placeholder="Stock code"
        className="w-36"
        aria-label="Filter by stock code"
      />
      {/* Hidden submit so Enter applies text filters. */}
      <button type="submit" className="sr-only">
        Apply filters
      </button>
      {hasFilters && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => router.replace("/transactions")}
        >
          <X className="mr-1 h-4 w-4" aria-hidden />
          Clear
        </Button>
      )}
    </form>
  );
}
