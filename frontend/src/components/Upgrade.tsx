import { ArrowRight, Gauge } from "lucide-react";
import type { LimitKey } from "../lib/api";
import { LIMIT_LABELS } from "../lib/plans";
import { ButtonLink, cx } from "./ui";

/** Shown in place of a result when the plan's limit is reached (HTTP 402 quota_exceeded). */
export function UpgradeNotice({ limit, message, className }: { limit: string; message?: string; className?: string }) {
  const what = LIMIT_LABELS[limit as LimitKey]?.label.toLowerCase();
  return (
    <div className={cx("flex flex-wrap items-start gap-3 rounded-md border border-signal/40 bg-signal-soft px-4 py-3", className)} role="alert">
      <Gauge className="mt-0.5 size-4 shrink-0 text-signal-text" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink">{what ? `You've reached your plan's limit for ${what}.` : "This needs a higher plan."}</p>
        {message && <p className="mt-0.5 text-sm text-ink-2">{message}</p>}
      </div>
      <ButtonLink to="/pricing" size="sm" variant="primary">
        See plans <ArrowRight className="size-3.5" aria-hidden="true" />
      </ButtonLink>
    </div>
  );
}
