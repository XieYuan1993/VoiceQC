"use client";

import { HelpCircle } from "lucide-react";
import * as React from "react";

import type { StatusMeta } from "@/lib/status-meta";
import { cn } from "@/lib/utils";

/** A small "what do these mean?" toggle that expands an inline legend. Inline
 * (not a popover) so it never clips inside overflow-hidden cards. */
export function StatusLegend({
  items,
  label = "What do these mean?",
  className,
}: {
  items: StatusMeta[];
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className={className}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <HelpCircle className="h-3.5 w-3.5" aria-hidden />
        {label}
      </button>
      {open && (
        <dl className="mt-2 grid gap-x-5 gap-y-1.5 rounded-lg border bg-muted/30 p-3 sm:grid-cols-2">
          {items.map((i) => (
            <div key={i.label} className="text-xs leading-relaxed">
              <dt className="inline font-medium text-foreground">{i.label}</dt>
              <dd className="inline text-muted-foreground"> — {i.description}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
