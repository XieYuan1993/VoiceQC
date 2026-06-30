import { cn } from "@/lib/utils";

/** Tiny inline trend line from a series of (possibly null) values. Coloured by
 * direction: green if the last point is >= the first, red otherwise. */
export function Sparkline({
  values,
  width = 64,
  height = 20,
  className,
}: {
  values: (number | null | undefined)[];
  width?: number;
  height?: number;
  className?: string;
}) {
  const pts = values
    .map((v, i) => ({ v, i }))
    .filter((p): p is { v: number; i: number } => p.v != null && Number.isFinite(p.v));

  if (pts.length === 0) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }

  const span = values.length > 1 ? values.length - 1 : 1;
  const min = Math.min(...pts.map((p) => p.v));
  const max = Math.max(...pts.map((p) => p.v));
  const range = max - min || 1;
  const pad = 2.5;
  const x = (i: number) => (i / span) * (width - pad * 2) + pad;
  const y = (v: number) => height - pad - ((v - min) / range) * (height - pad * 2);

  if (pts.length === 1) {
    return (
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className={className}
        role="img"
        aria-label="single data point"
      >
        <circle cx={width / 2} cy={height / 2} r={2.5} className="fill-muted-foreground" />
      </svg>
    );
  }

  const up = pts[pts.length - 1].v >= pts[0].v;
  const tone = up ? "stroke-emerald-500" : "stroke-red-500";
  const dotTone = up ? "fill-emerald-500" : "fill-red-500";
  const last = pts[pts.length - 1];
  const d = pts
    .map((p, idx) => `${idx === 0 ? "M" : "L"} ${x(p.i).toFixed(1)} ${y(p.v).toFixed(1)}`)
    .join(" ");

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      role="img"
      aria-label="trend sparkline"
    >
      <path
        d={d}
        fill="none"
        className={cn(tone)}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={x(last.i)} cy={y(last.v)} r={1.8} className={dotTone} />
    </svg>
  );
}
