import { ArrowRight, Bell } from "lucide-react";
import type { StateStat } from "../lib/api";
import { formatCount, formatInr } from "../lib/format";
import { SectorIcon, sectorMeta } from "../lib/sectors";
import { ButtonLink, cx } from "./ui";

/** Readout for the state picked on the map, with the two things to do next. */
export function StatePanel({ stat, state }: { stat?: StateStat; state: string }) {
  const cells = [
    { label: "Open", value: formatCount(stat?.open) },
    { label: "Closing ≤ 7d", value: formatCount(stat?.closing_this_week) },
  ];
  return (
    <div>
      <p className="label">Selected state</p>
      <h3 className="mt-2 text-2xl font-semibold text-ink">{state}</h3>
      <dl className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line">
        {cells.map((c) => (
          <div key={c.label} className="bg-surface px-3.5 py-3">
            <dt className="label">{c.label}</dt>
            <dd className="num mt-1.5 text-2xl font-medium text-ink">{c.value}</dd>
          </div>
        ))}
        <div className="col-span-2 bg-surface px-3.5 py-3">
          <dt className="label">Disclosed value</dt>
          <dd className="num mt-1.5 text-lg text-ink">{formatInr(stat?.value_inr)}</dd>
        </div>
      </dl>
      {stat?.top_sector && (
        <p className="mt-4 flex items-center gap-2 text-sm text-ink-2">
          <span className="label">Most common</span>
          <span className="inline-flex items-center gap-1.5 text-ink">
            <SectorIcon slug={stat.top_sector} />
            {sectorMeta(stat.top_sector).label}
          </span>
        </p>
      )}
      <div className="mt-6 flex flex-wrap gap-2">
        <ButtonLink variant="primary" to={`/tenders?state=${encodeURIComponent(state)}`}>
          View tenders <ArrowRight className="size-4" aria-hidden="true" />
        </ButtonLink>
        <ButtonLink to={`/alerts?state=${encodeURIComponent(state)}`}>
          <Bell className="size-4" aria-hidden="true" /> Alert me
        </ButtonLink>
      </div>
    </div>
  );
}

/** The states with the most tenders by `metric`, as a ranked list; picking one selects it. */
export function TopStates({
  data,
  selected,
  onSelect,
  metric = "open",
  count = 6,
}: {
  data?: StateStat[];
  selected?: string;
  onSelect: (s: string) => void;
  metric?: "open" | "closing_this_week";
  count?: number;
}) {
  const top = [...(data ?? [])].sort((a, b) => b[metric] - a[metric]).slice(0, count);
  const max = top[0]?.[metric] || 1;
  if (!top.length) return null;
  return (
    <div className="mt-8 border-t border-line pt-6">
      <p className="label mb-3 flex justify-between">
        <span>{metric === "open" ? "Most open tenders" : "Most closing in 7 days"}</span>
        <span>{metric === "open" ? "Open" : "≤ 7d"}</span>
      </p>
      <ol>
        {top.map((s, i) => {
          const on = s.state === selected;
          return (
            <li key={s.state}>
              <button
                onClick={() => onSelect(s.state)}
                aria-pressed={on}
                className={cx(
                  "relative grid w-full grid-cols-[24px_1fr_auto] items-center gap-x-3 gap-y-1.5 py-2 pr-1 pl-3 text-left text-sm transition-colors hover:bg-surface-2/70",
                  on && "bg-surface-2/70",
                )}
              >
                <span className={cx("absolute inset-y-1 left-0 w-0.5 bg-signal transition-opacity", on ? "opacity-100" : "opacity-0")} aria-hidden="true" />
                <span className="num text-xs text-ink-3">{String(i + 1).padStart(2, "0")}</span>
                <span className={on ? "font-medium text-ink" : "text-ink-2"}>{s.state}</span>
                <span className="num text-ink">{formatCount(s[metric])}</span>
                <span className="bar col-start-2 col-end-4" aria-hidden="true">
                  <span style={{ width: `${(s[metric] / max) * 100}%` }} />
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
