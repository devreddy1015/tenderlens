import { quotaExceeded } from "./api";

/** Every HTTP 402 quota_exceeded ends in the same upgrade prompt. Errors that a page shows
 *  inline (an UpgradeNotice next to the form) are marked `meta: { inlineQuota: true }` on
 *  their mutation; everything else is reported here and the dialog in the Layout opens. */

export interface QuotaInfo {
  limit: string;
  message: string;
}

const bus = new EventTarget();
const EVENT = "quota-exceeded";

/** Open the upgrade dialog if `e` is a quota error. Returns whether it was one. */
export function reportQuota(e: unknown): boolean {
  const q = quotaExceeded(e);
  if (q) bus.dispatchEvent(new CustomEvent<QuotaInfo>(EVENT, { detail: q }));
  return !!q;
}

export function onQuota(fn: (q: QuotaInfo) => void): () => void {
  const h = (e: Event) => fn((e as CustomEvent<QuotaInfo>).detail);
  bus.addEventListener(EVENT, h);
  return () => bus.removeEventListener(EVENT, h);
}

/** Feature limits are on/off; the others are monthly or absolute caps. */
const FEATURES = new Set(["export", "api"]);

/** "Copilot questions" → "Copilot questions", "Team seats" → "team seats", "CSV export" stays. */
export function lowerLabel(label: string): string {
  if (/^[A-Z]{2}/.test(label) || label.startsWith("Copilot")) return label;
  return label.charAt(0).toLowerCase() + label.slice(1);
}

/** The one headline every upgrade prompt uses. */
export function upgradeHeadline(limit: string, label: string | undefined): string {
  if (!label) return "This needs a higher plan.";
  if (FEATURES.has(limit)) return `${label} isn't included in your plan.`;
  return `You've reached your plan's limit for ${lowerLabel(label)}.`;
}
