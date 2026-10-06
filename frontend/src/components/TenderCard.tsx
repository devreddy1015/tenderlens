import { Check, Copy, MapPin } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import type { Tender } from "../lib/api";
import { closesIn, countdown, formatDate, formatInr, windowUsed } from "../lib/format";
import { useSignedIn } from "../lib/queries";
import { SectorIcon, sectorMeta } from "../lib/sectors";
import { TrackChip } from "./TrackButton";
import { cx, Skeleton } from "./ui";

/** Time left to bid: a mono readout, the share of the bidding window used, and the date. */
export function Countdown({
  closes,
  published,
  compact,
  className,
}: {
  closes: string;
  published?: string;
  /** true hides the date; "mobile" hides it below the md breakpoint only. */
  compact?: boolean | "mobile";
  className?: string;
}) {
  const due = countdown(closes);
  const used = published ? windowUsed(published, closes) : null;
  return (
    <div className={className} title={closesIn(closes).text}>
      <p className={cx("num text-[15px] font-medium", due.closed ? "text-ink-3" : due.urgent ? "text-critical" : "text-ink")}>
        {due.text}
        {!due.closed && <span className="ml-1.5 font-sans text-xs font-normal text-ink-3">left</span>}
      </p>
      {used !== null && !due.closed && (
        <div className={cx("bar mt-1.5 w-full max-w-28", due.urgent && "bar-critical")} aria-hidden="true">
          <span style={{ width: `${Math.max(4, Math.round(used * 100))}%` }} />
        </div>
      )}
      {compact !== true && <p className={cx("num mt-1.5 text-xs text-ink-3", compact === "mobile" && "hidden md:block")}>{formatDate(closes)}</p>}
    </div>
  );
}

export function CopyId({ id, className }: { id: string; className?: string }) {
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
      className={cx("num inline-flex items-center gap-1.5 rounded px-1 py-0.5 text-xs text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink", className)}
      title="Copy tender ID (search it on the official portal)"
    >
      {id}
      {done ? <Check className="size-3.5 text-good" aria-label="Copied" /> : <Copy className="size-3 opacity-70" aria-hidden="true" />}
    </button>
  );
}

function Meta({ t }: { t: Tender }) {
  return (
    <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-3">
      <span className="inline-flex items-center gap-1.5 text-ink-2">
        <SectorIcon slug={t.sector} className="size-3.5" />
        {sectorMeta(t.sector).label}
      </span>
      {t.state && (
        <>
          <span aria-hidden="true">·</span>
          <span className="inline-flex items-center gap-1">
            <MapPin className="size-3" aria-hidden="true" />
            {t.state}
          </span>
        </>
      )}
    </p>
  );
}

/** Column heads for a list of TenderRows, on wide screens. */
export function TenderListHeader() {
  return (
    <div className="label hidden grid-cols-[1fr_130px_150px] gap-x-6 border-b border-line px-5 py-2.5 md:grid" aria-hidden="true">
      <span>Tender</span>
      <span className="text-right">Value</span>
      <span>Closes</span>
    </div>
  );
}

/** One tender as a dense, scannable row: what and who, how much, how long left. */
export function TenderRow({ t }: { t: Tender }) {
  const signedIn = useSignedIn();
  return (
    <article className="group relative grid grid-cols-[1fr_auto] gap-x-6 gap-y-3 border-b border-line px-4 py-4 transition-colors last:border-b-0 hover:bg-surface-2/60 sm:px-5 md:grid-cols-[1fr_130px_150px]">
      <span className="absolute inset-y-0 left-0 w-0.5 bg-signal opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
      <div className="col-span-2 min-w-0 md:col-span-1">
        <Meta t={t} />
        <h3 className="mt-1.5 line-clamp-2 text-[15px] leading-snug font-medium text-ink">
          <Link to={`/tenders/${t.id}`} className="after:absolute after:inset-0">
            {t.title}
          </Link>
        </h3>
        <p className="mt-1 line-clamp-1 text-sm text-ink-2">{t.buyer?.canonical_name ?? t.buyer_raw}</p>
        {/* Wrappers, because a display utility on CopyId itself would clash with its inline-flex. */}
        <div className={cx("relative z-10 mt-1.5 -ml-1 items-center gap-2", signedIn ? "flex" : "hidden md:flex")}>
          <span className="hidden md:block">
            <CopyId id={t.source_tender_id} />
          </span>
          <TrackChip tender={t} className="ml-1" />
        </div>
      </div>
      <div className="self-end md:self-auto md:text-right">
        <p className={cx("num text-[15px]", t.value_inr ? "font-medium text-ink" : "text-ink-3")}>{formatInr(t.value_inr, { short: true })}</p>
        {t.emd_inr && Number(t.emd_inr) > 0 && <p className="num text-xs text-ink-3 md:mt-1">EMD {formatInr(t.emd_inr, { short: true })}</p>}
      </div>
      <Countdown closes={t.closes_at} published={t.published_at} compact="mobile" className="self-end text-right md:self-auto md:text-left [&_.bar]:ml-auto md:[&_.bar]:ml-0" />
    </article>
  );
}

export function TenderRowSkeleton() {
  return (
    <div className="grid gap-x-6 gap-y-3 border-b border-line px-5 py-4 last:border-b-0 md:grid-cols-[1fr_130px_150px]">
      <div>
        <Skeleton className="mb-2.5 h-3 w-40" />
        <Skeleton className="mb-2 h-4 w-full" />
        <Skeleton className="h-3.5 w-1/2" />
      </div>
      <Skeleton className="h-5 w-20 md:ml-auto" />
      <Skeleton className="h-9 w-28" />
    </div>
  );
}

/** A tender in a grid cell, for related or featured tenders. */
export function TenderCard({ t }: { t: Tender }) {
  return (
    <article className="panel group relative flex flex-col p-4 transition-colors hover:border-line-strong">
      <div className="flex items-start justify-between gap-2">
        <Meta t={t} />
        <TrackChip tender={t} className="-mt-0.5 shrink-0" />
      </div>
      <h3 className="mt-2 line-clamp-2 text-[15px] leading-snug font-medium text-ink">
        <Link to={`/tenders/${t.id}`} className="after:absolute after:inset-0 group-hover:underline group-hover:decoration-line-strong group-hover:underline-offset-4">
          {t.title}
        </Link>
      </h3>
      <p className="mt-1 line-clamp-1 text-sm text-ink-2">{t.buyer?.canonical_name ?? t.buyer_raw}</p>
      <div className="min-h-4 flex-1" aria-hidden="true" />
      <div className="flex items-end justify-between gap-3 border-t border-line pt-3">
        <div>
          <p className="label">Value</p>
          <p className={cx("num mt-1 text-[15px]", t.value_inr ? "font-medium text-ink" : "text-ink-3")}>{formatInr(t.value_inr, { short: true })}</p>
        </div>
        <Countdown closes={t.closes_at} published={t.published_at} compact className="text-right [&_.bar]:ml-auto" />
      </div>
    </article>
  );
}
