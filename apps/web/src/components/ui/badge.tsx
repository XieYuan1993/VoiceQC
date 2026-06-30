import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

// Status colors (emerald/amber/blue/red/...) are deliberate Tailwind palette
// picks, per the globals.css note: semantic colors ride utility classes, not
// theme variables.
const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "text-foreground",
        destructive:
          "border-transparent bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-300",
        success:
          "border-transparent bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300",
        warning:
          "border-transparent bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300",
        info: "border-transparent bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300",
        violet:
          "border-transparent bg-violet-100 text-violet-800 dark:bg-violet-950/60 dark:text-violet-300",
        orange:
          "border-transparent bg-orange-100 text-orange-800 dark:bg-orange-950/60 dark:text-orange-300",
        neutral:
          "border-transparent bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
