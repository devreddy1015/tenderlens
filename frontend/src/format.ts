const LAKH = 100_000;
const CRORE = 10_000_000;

/** ₹ amounts the way Indian procurement documents write them: lakh and crore. */
export function formatInr(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  if (n === 0) return "Not disclosed";
  if (n >= CRORE) return `₹${trim(n / CRORE)} crore`;
  if (n >= LAKH) return `₹${trim(n / LAKH)} lakh`;
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function trim(x: number): string {
  return x.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Kolkata",
  });
}

export function closesIn(iso: string, now: Date = new Date()): { text: string; urgent: boolean } {
  const ms = new Date(iso).getTime() - now.getTime();
  if (ms < 0) return { text: "Closed", urgent: false };
  const hours = Math.floor(ms / 3_600_000);
  if (hours < 24) return { text: `Closes in ${hours}h`, urgent: true };
  const days = Math.floor(hours / 24);
  return { text: `Closes in ${days} day${days === 1 ? "" : "s"}`, urgent: days <= 3 };
}
