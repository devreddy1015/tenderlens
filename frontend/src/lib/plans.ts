import type { Interval, LimitKey, LimitValue, Plan } from "./api";
import { formatCount } from "./format";

/** How each plan limit reads to a customer, in the order the pricing table lists them.
 *  Mirrors billing.plans.LIMIT_KEYS. */
export const LIMIT_LABELS: Record<LimitKey, { label: string; per?: string }> = {
  questions_per_month: { label: "Copilot questions", per: "a month" },
  documents_per_month: { label: "Document uploads", per: "a month" },
  alerts: { label: "Email alerts" },
  seats: { label: "Team seats" },
  export: { label: "CSV export" },
  api: { label: "API access" },
};

/** "Unlimited", "Included", "Not included" or the cap. */
export function describeLimit(v: LimitValue | undefined): string {
  if (v === null) return "Unlimited";
  if (v === true) return "Included";
  if (v === undefined || v === false || v === 0) return "Not included";
  return formatCount(v);
}

/** Whether a plan includes a feature at all (any cap above zero counts). */
export function includes(plan: Plan | undefined, key: LimitKey): boolean {
  const v = plan?.limits[key];
  return v === null || v === true || (typeof v === "number" && v > 0);
}

/** The plan's price for one billing interval; null when it is priced per customer. */
export function priceFor(plan: Plan, interval: Interval): number | null {
  const p = interval === "year" ? plan.price_inr_year : plan.price_inr_month;
  return p === null || p === undefined ? null : Number(p);
}

/** What a yearly price comes to per month, rounded down to the rupee. */
export function perMonth(plan: Plan, interval: Interval): number | null {
  const p = priceFor(plan, interval);
  return p === null ? null : interval === "year" ? Math.floor(p / 12) : p;
}

/** Percent saved by paying yearly instead of twelve months; 0 when it isn't cheaper. */
export function yearlySaving(plan: Plan): number {
  const month = Number(plan.price_inr_month);
  const year = Number(plan.price_inr_year);
  if (!(month > 0) || !(year > 0)) return 0;
  return Math.max(0, Math.round((1 - year / (month * 12)) * 100));
}

/** Usage against a numeric cap, for a meter. `fraction` is null when there is nothing to fill. */
export function meter(used: number, limit: LimitValue | undefined): { fraction: number | null; text: string; full: boolean } {
  if (limit === null) return { fraction: null, text: `${formatCount(used)} used · unlimited`, full: false };
  if (typeof limit !== "number" || limit <= 0) return { fraction: null, text: "Not on this plan", full: false };
  return { fraction: Math.min(1, used / limit), text: `${formatCount(used)} of ${formatCount(limit)}`, full: used >= limit };
}

/** Plans cheapest first; plans priced per customer ("talk to us") last. */
export function byPrice(plans: Plan[]): Plan[] {
  const key = (p: Plan) => (p.price_inr_month === null ? Number.POSITIVE_INFINITY : Number(p.price_inr_month));
  return [...plans].sort((a, b) => key(a) - key(b));
}
