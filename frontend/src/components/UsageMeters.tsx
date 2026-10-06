import type { LimitKey } from "../lib/api";
import { LIMIT_LABELS, meter } from "../lib/plans";
import { useWorkspace } from "../lib/queries";
import { cx, Skeleton } from "./ui";

/** This month's usage against the plan's caps, one thin bar per limit. */
export function UsageMeters({ keys, className }: { keys: LimitKey[]; className?: string }) {
  const ws = useWorkspace();
  if (ws.isLoading) return <Skeleton className={cx("h-20 w-full", className)} />;
  if (!ws.data) return null;
  const { plan, usage } = ws.data;
  return (
    <dl className={cx("space-y-3", className)}>
      {keys.map((k) => {
        const m = meter(usage[k] ?? 0, plan.limits[k]);
        return (
          <div key={k}>
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <dt className="text-ink-2">
                {LIMIT_LABELS[k].label}
                {LIMIT_LABELS[k].per && <span className="text-ink-3"> · this month</span>}
              </dt>
              <dd className={cx("num", m.full ? "text-critical" : "text-ink")}>{m.text}</dd>
            </div>
            {m.fraction !== null && (
              <div
                className={cx("bar mt-1.5", m.full && "bar-critical")}
                role="meter"
                aria-label={LIMIT_LABELS[k].label}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(m.fraction * 100)}
              >
                <span style={{ width: `${Math.max(2, m.fraction * 100)}%` }} />
              </div>
            )}
          </div>
        );
      })}
    </dl>
  );
}
