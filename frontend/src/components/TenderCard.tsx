import { Building, CalendarClock, Check, Copy, MapPin } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import type { Tender } from "../lib/api";
import { closesIn, formatInr, windowUsed } from "../lib/format";
import { SectorIcon, sectorMeta } from "../lib/sectors";
import { cx, Skeleton } from "./ui";

export function ClosingBadge({ closes, published }: { closes: string; published?: string }) {
  const due = closesIn(closes);
  const used = published ? windowUsed(published, closes) : null;
  return (
    <span className="inline-flex flex-col gap-1">
      <span
        className={cx(
          "inline-flex items-center gap-1.5 text-sm font-medium",
          due.urgent ? "text-critical" : due.closed ? "text-ink-3" : "text-ink-2",
        )}
      >
        <CalendarClock className="size-4" aria-hidden="true" />
        {due.text}
      </span>
      {used !== null && !due.closed && (
        <span className="h-1 w-28 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
          <span className={cx("block h-full rounded-full", due.urgent ? "bg-critical" : "bg-brand")} style={{ width: `${Math.round(used * 100)}%` }} />
        </span>
      )}
    </span>
  );
}

export function CopyId({ id }: { id: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        navigator.clipboard?.writeText(id).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        });
      }}
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-xs text-ink-3 hover:bg-surface-2 hover:text-ink"
      title="Copy tender ID (search it on the official portal)"
    >
      {id}
      {done ? <Check className="size-3.5 text-good" aria-label="Copied" /> : <Copy className="size-3.5" aria-hidden="true" />}
    </button>
  );
}

export function TenderCard({ t, compact }: { t: Tender; compact?: boolean }) {
  const sector = sectorMeta(t.sector);
  return (
    <article className="group relative rounded-2xl border border-line bg-surface p-4 transition-shadow hover:shadow-lg hover:shadow-black/5 sm:p-5">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2.5 py-1 font-medium text-brand">
          <SectorIcon slug={t.sector} className="size-3.5" />
          {sector.label}
        </span>
        {t.state && (
          <span className="inline-flex items-center gap-1 text-ink-3">
            <MapPin className="size-3.5" aria-hidden="true" />
            {t.state}
          </span>
        )}
      </div>
      <h3 className={cx("font-semibold leading-snug text-ink", compact ? "line-clamp-2 text-[15px]" : "line-clamp-3 text-base")}>
        <Link to={`/tenders/${t.id}`} className="after:absolute after:inset-0 group-hover:text-brand">
          {t.title}
        </Link>
      </h3>
      <p className="mt-1.5 flex items-start gap-1.5 text-sm text-ink-2">
        <Building className="mt-0.5 size-4 shrink-0 text-ink-3" aria-hidden="true" />
        <span className="line-clamp-1">{t.buyer?.canonical_name ?? t.buyer_raw}</span>
      </p>
      <div className="mt-4 flex flex-wrap items-end justify-between gap-3">
        <div className="flex gap-6">
          <div>
            <p className="text-xs text-ink-3">Value</p>
            <p className="font-semibold text-ink tabular-nums">{formatInr(t.value_inr)}</p>
          </div>
          {!compact && (
            <div>
              <p className="text-xs text-ink-3">EMD</p>
              <p className="text-ink-2 tabular-nums">{formatInr(t.emd_inr)}</p>
            </div>
          )}
        </div>
        <ClosingBadge closes={t.closes_at} published={t.published_at} />
      </div>
      {!compact && (
        <div className="relative z-10 mt-3 border-t border-line pt-2">
          <CopyId id={t.source_tender_id} />
        </div>
      )}
    </article>
  );
}

export function TenderCardSkeleton() {
  return (
    <div className="rounded-2xl border border-line bg-surface p-5">
      <Skeleton className="mb-3 h-5 w-32 rounded-full" />
      <Skeleton className="mb-2 h-5 w-full" />
      <Skeleton className="mb-4 h-4 w-2/3" />
      <div className="flex justify-between">
        <Skeleton className="h-9 w-24" />
        <Skeleton className="h-6 w-28" />
      </div>
    </div>
  );
}
