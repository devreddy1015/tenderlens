import { ArrowRight, Gauge } from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation } from "react-router";
import type { LimitKey, Plan } from "../lib/api";
import { byPrice, describeLimit, LIMIT_LABELS } from "../lib/plans";
import { usePlans, useWorkspace } from "../lib/queries";
import { lowerLabel, onQuota, type QuotaInfo, upgradeHeadline } from "../lib/upgrade";
import { Button, ButtonLink, cx, Dialog } from "./ui";

/** The cheapest plan that gives more of `limit` than the current one. */
function nextPlan(plans: Plan[] | undefined, current: Plan | undefined, limit: string): Plan | undefined {
  const k = limit as LimitKey;
  const amount = (p: Plan | undefined) => {
    const v = p?.limits[k];
    return v === null ? Infinity : v === true ? 1 : typeof v === "number" ? v : 0;
  };
  const have = amount(current);
  return byPrice(plans ?? []).find((p) => p.code !== current?.code && amount(p) > have);
}

function useSuggestion(limit: string): string | null {
  const plans = usePlans();
  const ws = useWorkspace();
  const p = nextPlan(plans.data, ws.data?.plan, limit);
  if (!p) return null;
  const v = describeLimit(p.limits[limit as LimitKey]);
  const what = LIMIT_LABELS[limit as LimitKey];
  if (!what) return `The ${p.name} plan raises this limit.`;
  return v === "Included" ? `${p.name} includes ${lowerLabel(what.label)}.` : `${p.name} gives you ${v.toLowerCase()} ${lowerLabel(what.label)}${what.per ? ` ${what.per}` : ""}.`;
}

/** Shown in place of a result when the plan's limit is reached (HTTP 402 quota_exceeded). */
export function UpgradeNotice({ limit, message, className }: { limit: string; message?: string; className?: string }) {
  const headline = upgradeHeadline(limit, LIMIT_LABELS[limit as LimitKey]?.label);
  const suggestion = useSuggestion(limit);
  return (
    <div className={cx("flex flex-wrap items-start gap-3 rounded-md border border-signal/40 bg-signal-soft px-4 py-3", className)} role="alert">
      <Gauge className="mt-0.5 size-4 shrink-0 text-signal-text" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink">{headline}</p>
        {message && message !== headline && <p className="mt-0.5 text-sm text-ink-2">{message}</p>}
        {suggestion && <p className="mt-0.5 text-sm text-ink-2">{suggestion}</p>}
      </div>
      <ButtonLink to="/pricing" size="sm" variant="primary">
        See plans <ArrowRight className="size-3.5" aria-hidden="true" />
      </ButtonLink>
    </div>
  );
}

/** Mounted once in the Layout: opens for any 402 that no page shows inline. */
export function UpgradeDialogHost() {
  const [q, setQ] = useState<QuotaInfo | null>(null);
  const { pathname } = useLocation();
  useEffect(() => onQuota(setQ), []);
  // "See plans" navigates; the prompt shouldn't follow you to the pricing page.
  useEffect(() => setQ(null), [pathname]);
  return (
    <Dialog open={q !== null} onClose={() => setQ(null)} title="Upgrade to continue">
      {q && (
        <div className="space-y-4">
          <UpgradeNotice limit={q.limit} message={q.message} />
          <p className="text-xs text-ink-3">Prices are published and checkout is self-serve; you can cancel any time from Workspace → Billing.</p>
          <div className="flex justify-end border-t border-line pt-4">
            <Button variant="ghost" onClick={() => setQ(null)}>
              Not now
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
