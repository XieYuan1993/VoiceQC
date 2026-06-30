"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { cn } from "@/lib/utils";

/** Table row that navigates on click (tr can't be an <a>). */
export function LinkedRow({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  return (
    <tr
      tabIndex={0}
      onClick={() => router.push(href)}
      onKeyDown={(e) => {
        if (e.key === "Enter") router.push(href);
      }}
      className={cn(
        "cursor-pointer border-b transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none",
        className,
      )}
    >
      {children}
    </tr>
  );
}
