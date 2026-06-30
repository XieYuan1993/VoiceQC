"use client";

import { X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

// Right-anchored slide-over in the shadcn Sheet API shape, hand-rolled like
// ui/dialog.tsx so Phase 3 still doesn't grow the dependency tree. Escape and
// backdrop-click close; body scroll locks while open.

const SheetContext = React.createContext<{ onOpenChange: (open: boolean) => void }>({
  onOpenChange: () => {},
});

interface SheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}

function Sheet({ open, onOpenChange, children }: SheetProps) {
  React.useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onOpenChange(false);
    }
    document.addEventListener("keydown", onKeyDown);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onOpenChange]);

  if (!open) return null;
  return (
    <SheetContext.Provider value={{ onOpenChange }}>
      <div className="fixed inset-0 z-50 flex justify-end">
        <div
          aria-hidden
          className="fixed inset-0 bg-black/50 backdrop-blur-sm"
          onClick={() => onOpenChange(false)}
        />
        {children}
      </div>
    </SheetContext.Provider>
  );
}

function SheetContent({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  const { onOpenChange } = React.useContext(SheetContext);
  return (
    <div
      role="dialog"
      aria-modal="true"
      className={cn(
        "relative z-50 flex h-full w-full max-w-2xl flex-col gap-4 overflow-y-auto border-l bg-background p-6 shadow-lg",
        className,
      )}
      {...props}
    >
      {children}
      <button
        type="button"
        aria-label="Close"
        onClick={() => onOpenChange(false)}
        className="absolute right-4 top-4 rounded-sm text-muted-foreground transition-colors hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

function SheetHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col space-y-1.5 pr-6 text-left", className)} {...props} />;
}

function SheetTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cn("text-lg font-semibold leading-none tracking-tight", className)}
      {...props}
    />
  );
}

function SheetDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...props} />;
}

export { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle };
