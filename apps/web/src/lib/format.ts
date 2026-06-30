// Deterministic (locale-free) display formatting, safe for SSR + hydration.

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** ISO datetime -> local "YYYY-MM-DD HH:mm". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(
    d.getHours(),
  )}:${pad2(d.getMinutes())}`;
}

/** Seconds -> "m:ss" (or "h:mm:ss" past an hour). */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}:${pad2(m)}:${pad2(s)}` : `${m}:${pad2(s)}`;
}

/** Milliseconds -> "mm:ss" transcript timestamp. */
export function formatMs(ms: number): string {
  const total = Math.floor(ms / 1000);
  return `${pad2(Math.floor(total / 60))}:${pad2(total % 60)}`;
}

/** Today's local date as "YYYY-MM-DD" — initial value for date inputs. */
export function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let v = bytes;
  let u = -1;
  do {
    v /= 1024;
    u += 1;
  } while (v >= 1024 && u < units.length - 1);
  return `${v >= 100 ? Math.round(v) : v.toFixed(1)} ${units[u]}`;
}
