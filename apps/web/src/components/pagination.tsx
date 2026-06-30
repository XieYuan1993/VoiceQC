import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

function PageLink({ disabled, href, label }: { disabled: boolean; href: string; label: string }) {
  const cls = cn(buttonVariants({ variant: "outline", size: "sm" }));
  if (disabled) {
    return (
      <span aria-disabled className={cn(cls, "pointer-events-none opacity-50")}>
        {label}
      </span>
    );
  }
  return (
    <Link href={href} className={cls}>
      {label}
    </Link>
  );
}

/** Link-based pager for server-rendered lists (state lives in the URL). */
export function Pagination({
  page,
  pageSize,
  total,
  makeHref,
  className,
}: {
  page: number;
  pageSize: number;
  total: number;
  makeHref: (page: number) => string;
  className?: string;
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className={cn("flex items-center justify-between gap-4", className)}>
      <p className="text-sm text-muted-foreground">
        Page {page} of {pageCount} · {total} total
      </p>
      {pageCount > 1 && (
        <div className="flex items-center gap-2">
          <PageLink disabled={page <= 1} href={makeHref(page - 1)} label="Previous" />
          <PageLink disabled={page >= pageCount} href={makeHref(page + 1)} label="Next" />
        </div>
      )}
    </div>
  );
}
