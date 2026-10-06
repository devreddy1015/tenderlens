import { useMemo, useRef, useState } from "react";
import type { StateStat } from "../lib/api";
import indiaData from "../data/india-states.json";
import { formatCount, formatInr } from "../lib/format";
import { SectorIcon, sectorMeta } from "../lib/sectors";
import { cx } from "./ui";

type Region = { name: string; d: string; cx: number; cy: number };
const INDIA = indiaData as { viewBox: string; attribution: string; states: Region[] };

// Regions too small to hover on a phone get a marker at their centre as well.
const SMALL = new Set(["Delhi", "Chandigarh", "Puducherry", "Lakshadweep", "Goa", "Dadra and Nagar Haveli and Daman and Diu"]);
const STEPS = ["var(--map-2)", "var(--map-3)", "var(--map-4)", "var(--map-5)", "var(--map-6)", "var(--map-7)"];

function nice(x: number): number {
  if (x < 10) return Math.max(1, Math.round(x));
  const p = 10 ** Math.floor(Math.log10(x));
  return Math.round(x / (p / 2)) * (p / 2);
}

/** Quantile class breaks (equal number of states per colour), rounded to readable numbers. */
export function classBreaks(values: number[], classes = STEPS.length): number[] {
  const v = values.filter((x) => x > 0).sort((a, b) => a - b);
  if (v.length === 0) return [];
  const breaks: number[] = [];
  for (let i = 1; i < classes; i++) {
    const b = nice(v[Math.min(v.length - 1, Math.floor((i / classes) * v.length))]);
    if (b > (breaks.at(-1) ?? 0) && b > v[0]) breaks.push(b);
  }
  return breaks;
}

export function classOf(value: number, breaks: number[]): number {
  if (value <= 0) return -1;
  let i = 0;
  while (i < breaks.length && value >= breaks[i]) i++;
  return i;
}

export function IndiaMap({
  data,
  metric = "open",
  selected,
  onSelect,
  loading,
}: {
  data: StateStat[] | undefined;
  metric?: "open" | "closing_this_week";
  selected?: string;
  onSelect?: (state: string) => void;
  loading?: boolean;
}) {
  const byState = useMemo(() => Object.fromEntries((data ?? []).map((s) => [s.state, s])), [data]);
  const breaks = useMemo(() => classBreaks((data ?? []).map((s) => s[metric])), [data, metric]);
  const steps = STEPS.slice(STEPS.length - (breaks.length + 1));
  const [hover, setHover] = useState<{ name: string; x: number; y: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const fillFor = (name: string) => {
    const c = classOf(byState[name]?.[metric] ?? 0, breaks);
    return c < 0 ? "var(--map-empty)" : steps[c];
  };

  const place = (name: string, clientX: number, clientY: number) => {
    const r = box.current?.getBoundingClientRect();
    if (r) setHover({ name, x: clientX - r.left, y: clientY - r.top });
  };
  const placeAtCentre = (region: Region, el: Element) => {
    const svg = el.closest("svg");
    const r = box.current?.getBoundingClientRect();
    if (!svg || !r) return;
    const s = svg.getBoundingClientRect();
    const [, , w, h] = INDIA.viewBox.split(" ").map(Number);
    setHover({ name: region.name, x: s.left - r.left + (region.cx / w) * s.width, y: s.top - r.top + (region.cy / h) * s.height });
  };

  const hovered = hover ? byState[hover.name] : undefined;
  const label = (name: string) => {
    const s = byState[name];
    return `${name}: ${formatCount(s?.[metric] ?? 0)} ${metric === "open" ? "open tenders" : "closing this week"}`;
  };

  return (
    <div className="relative" ref={box} onPointerLeave={() => setHover(null)}>
      <svg
        viewBox={INDIA.viewBox}
        className={cx("h-auto w-full transition-opacity", loading && "opacity-50")}
        role="group"
        aria-label="Map of India: open tenders by state"
      >
        {INDIA.states.map((r) => {
          const active = r.name === selected || r.name === hover?.name;
          return (
            <path
              key={r.name}
              d={r.d}
              fill={fillFor(r.name)}
              stroke={active ? "var(--ink)" : "var(--map-stroke)"}
              strokeWidth={active ? 1.4 : 0.6}
              strokeLinejoin="round"
              className="cursor-pointer outline-none transition-[stroke-width]"
              tabIndex={0}
              role="button"
              aria-label={label(r.name)}
              aria-pressed={r.name === selected}
              onPointerMove={(e) => place(r.name, e.clientX, e.clientY)}
              onFocus={(e) => placeAtCentre(r, e.currentTarget)}
              onBlur={() => setHover(null)}
              onClick={() => onSelect?.(r.name)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect?.(r.name))}
            />
          );
        })}
        {INDIA.states
          .filter((r) => SMALL.has(r.name))
          .map((r) => (
            <circle
              key={`m-${r.name}`}
              cx={r.cx}
              cy={r.cy}
              r={5}
              fill={fillFor(r.name)}
              stroke={r.name === selected || r.name === hover?.name ? "var(--ink)" : "var(--map-stroke)"}
              strokeWidth={2}
              className="cursor-pointer"
              onPointerMove={(e) => place(r.name, e.clientX, e.clientY)}
              onClick={() => onSelect?.(r.name)}
              aria-hidden="true"
            />
          ))}
      </svg>

      {hover && (
        <div
          className="pointer-events-none absolute z-10 w-56 -translate-x-1/2 -translate-y-[calc(100%+14px)] rounded-md border border-line-strong bg-surface p-3 text-sm shadow-panel"
          style={{ left: Math.min(Math.max(hover.x, 112), (box.current?.clientWidth ?? 0) - 112), top: hover.y }}
          role="tooltip"
        >
          <p className="font-medium text-ink">{hover.name}</p>
          {hovered ? (
            <dl className="mt-2 space-y-1 border-t border-line pt-2 text-ink-2">
              <div className="flex justify-between gap-3">
                <dt>Open tenders</dt>
                <dd className="num font-medium text-ink">{formatCount(hovered.open)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>Closing in 7 days</dt>
                <dd className="num text-ink">{formatCount(hovered.closing_this_week)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>Disclosed value</dt>
                <dd className="num text-ink">{formatInr(hovered.value_inr, { short: true })}</dd>
              </div>
              {hovered.top_sector && (
                <div className="flex items-center gap-1.5 pt-1 text-xs text-ink-3">
                  <SectorIcon slug={hovered.top_sector} className="size-3.5" />
                  Mostly {sectorMeta(hovered.top_sector).label}
                </div>
              )}
            </dl>
          ) : (
            <p className="mt-1 text-ink-3">No open tenders right now</p>
          )}
        </div>
      )}

      <MapLegend breaks={breaks} steps={steps} metric={metric} />
    </div>
  );
}

function MapLegend({ breaks, steps, metric }: { breaks: number[]; steps: string[]; metric: string }) {
  if (steps.length === 0) return null;
  const ranges = steps.map((_, i) => {
    const lo = i === 0 ? 1 : breaks[i - 1];
    const hi = i < breaks.length ? breaks[i] - 1 : null;
    return hi === null ? `${formatCount(lo)}+` : lo === hi ? formatCount(lo) : `${formatCount(lo)}–${formatCount(hi)}`;
  });
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-ink-2" aria-label="Map legend">
      <span className="label mr-1">{metric === "open" ? "Open tenders" : "Closing in 7 days"}</span>
      <span className="flex items-center gap-1.5">
        <span className="size-2.5 rounded-[2px] border border-line-strong" style={{ background: "var(--map-empty)" }} />
        None
      </span>
      {steps.map((s, i) => (
        <span key={s} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[2px]" style={{ background: s }} />
          <span className="num">{ranges[i]}</span>
        </span>
      ))}
    </div>
  );
}

export const MAP_ATTRIBUTION = INDIA.attribution;
