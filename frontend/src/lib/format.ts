const LAKH = 100_000;
const CRORE = 10_000_000;

/** ₹ amounts the way Indian procurement documents write them: lakh and crore. */
export function formatInr(value: string | number | null | undefined, { short = false } = {}): string {
  if (value === null || value === undefined || value === "") return "Not disclosed";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n) || n === 0) return "Not disclosed";
  if (n >= CRORE) return `₹${trim(n / CRORE, short)}${short ? " Cr" : " crore"}`;
  if (n >= LAKH) return `₹${trim(n / LAKH, short)}${short ? " L" : " lakh"}`;
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function trim(x: number, short: boolean): string {
  return x.toLocaleString("en-IN", { maximumFractionDigits: short && x >= 100 ? 0 : 2 });
}

export function formatCount(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString("en-IN");
}

export function formatDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
    timeZone: "Asia/Kolkata",
  });
}

export function closesIn(iso: string, now: Date = new Date()): { text: string; urgent: boolean; closed: boolean } {
  const ms = new Date(iso).getTime() - now.getTime();
  if (ms < 0) return { text: "Closed", urgent: false, closed: true };
  const hours = Math.floor(ms / 3_600_000);
  if (hours < 24) return { text: hours < 1 ? "Closes within an hour" : `Closes in ${hours}h`, urgent: true, closed: false };
  const days = Math.floor(hours / 24);
  return { text: `Closes in ${days} day${days === 1 ? "" : "s"}`, urgent: days <= 3, closed: false };
}

export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "never";
  const mins = Math.round((now.getTime() - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** Fraction of the bidding window already used, 0..1, for the closing progress bar. */
export function windowUsed(publishedIso: string, closesIso: string, now: Date = new Date()): number {
  const start = new Date(publishedIso).getTime();
  const end = new Date(closesIso).getTime();
  if (end <= start) return 1;
  return Math.min(1, Math.max(0, (now.getTime() - start) / (end - start)));
}
