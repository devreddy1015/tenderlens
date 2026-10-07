import { CalendarDays, ChevronLeft, ChevronRight, ClipboardList, Search, SlidersHorizontal, Trash2 } from "lucide-react";
import { type DragEvent, useEffect, useState } from "react";
import { Link } from "react-router";
import { CalendarFeed } from "../components/CalendarFeed";
import { SignInGate } from "../components/SignIn";
import { Countdown } from "../components/TenderCard";
import { Button, ButtonLink, Card, cx, Dialog, EmptyState, Field, inputClass, PageHeader, Skeleton, Stat, Tag } from "../components/ui";
import { BID_STATUSES, type BidStatus, type BidTrack, errorMessage } from "../lib/api";
import { ACTIVE_STATUSES, BID_STATUS } from "../lib/bids";
import { countdown, formatCount, formatInr, formatRupees } from "../lib/format";
import { useMembers, usePipeline, usePipelineSummary, useRemoveTrack, useSignedIn, useUpdateTrack } from "../lib/queries";

const DRAG_TYPE = "application/x-tenderlens-bid";

/** Notes, our bid amount and the owner of one bid, saved together. */
function BidEditor({ b, onDone }: { b: BidTrack; onDone: () => void }) {
  const update = useUpdateTrack();
  const remove = useRemoveTrack();
  const members = useMembers();
  const [notes, setNotes] = useState(b.notes);
  const [amount, setAmount] = useState(b.bid_amount_inr ? String(Math.round(Number(b.bid_amount_inr))) : "");
  const [owner, setOwner] = useState(b.owner ? String(b.owner.id) : "");
  const [confirm, setConfirm] = useState(false);
  const amountOk = amount === "" || /^\d{1,15}$/.test(amount);

  return (
    <form
      className="mt-3 space-y-3 border-t border-line pt-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!amountOk) return;
        update.mutate(
          { id: b.id, patch: { notes, bid_amount_inr: amount === "" ? null : amount, owner: owner ? Number(owner) : null } },
          { onSuccess: onDone },
        );
      }}
    >
      <Field label="Owner">
        <select value={owner} onChange={(e) => setOwner(e.target.value)} className={cx(inputClass, "h-9")}>
          <option value="">Nobody yet</option>
          {/* owner is a user id; members are memberships carrying user_id. */}
          {b.owner && !members.data?.some((m) => m.user_id === b.owner!.id) && <option value={b.owner.id}>{b.owner.email}</option>}
          {members.data?.map((m) => (
            <option key={m.id} value={m.user_id}>
              {m.name || m.email}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Our bid (₹)" error={amountOk ? undefined : "Whole rupees, digits only."} hint={amount && amountOk ? formatInr(amount) : undefined}>
        <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/[,\s₹]/g, ""))} inputMode="numeric" className={cx(inputClass, "num h-9")} placeholder="e.g. 4500000" />
      </Field>
      <Field label="Notes">
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} maxLength={4000} className={cx(inputClass, "h-auto py-2")} placeholder="Site visit, pricing, who signs the DSC…" />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" variant="primary" disabled={update.isPending || !amountOk}>
          {update.isPending ? "Saving…" : "Save"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          Close
        </Button>
        {confirm ? (
          <span className="ml-auto inline-flex items-center gap-1.5 text-xs text-ink-2">
            Remove?
            <Button type="button" size="sm" variant="danger" className="h-7" onClick={() => remove.mutate(b.id)} disabled={remove.isPending}>
              Remove
            </Button>
          </span>
        ) : (
          <button type="button" onClick={() => setConfirm(true)} className="ml-auto inline-flex items-center gap-1 text-xs text-ink-3 hover:text-critical">
            <Trash2 className="size-3.5" aria-hidden="true" /> Remove
          </button>
        )}
      </div>
    </form>
  );
}

function BidCard({ b, onMove }: { b: BidTrack; onMove: (s: BidStatus) => void }) {
  const [editing, setEditing] = useState(false);
  const i = BID_STATUSES.indexOf(b.status);
  const prev = BID_STATUSES[i - 1];
  const next = BID_STATUSES[i + 1];
  const t = b.tender;
  return (
    <li
      draggable={!editing}
      onDragStart={(e) => {
        e.dataTransfer.setData(DRAG_TYPE, String(b.id));
        e.dataTransfer.effectAllowed = "move";
      }}
      className="rounded-md border border-line bg-surface p-3 shadow-[0_1px_0_rgb(0_0_0/0.02)] transition-colors hover:border-line-strong"
    >
      <Link to={`/tenders/${t.id}`} className="line-clamp-3 text-sm leading-snug font-medium text-ink decoration-line-strong underline-offset-4 hover:underline">
        {t.title}
      </Link>
      <p className="mt-1 line-clamp-1 text-xs text-ink-2">{t.buyer?.canonical_name ?? t.buyer_raw}</p>
      <div className="mt-2.5 flex items-end justify-between gap-3">
        <div>
          <p className="label text-[10px]">Value</p>
          <p className={cx("num mt-0.5 text-[13px]", t.value_inr ? "text-ink" : "text-ink-3")}>{formatInr(t.value_inr, { short: true })}</p>
        </div>
        <Countdown closes={t.closes_at} compact className="text-right [&>p]:text-[13px]" />
      </div>
      {(b.bid_amount_inr || b.owner || b.notes) && (
        <div className="mt-2.5 space-y-1 border-t border-line pt-2 text-xs text-ink-2">
          {b.bid_amount_inr && (
            <p>
              Our bid <span className="num text-ink">{formatRupees(b.bid_amount_inr)}</span>
            </p>
          )}
          {b.owner && <p className="truncate">Owner {b.owner.email}</p>}
          {b.notes && !editing && <p className="line-clamp-2 text-ink-3">{b.notes}</p>}
        </div>
      )}
      <div className="mt-2.5 flex items-center gap-1 border-t border-line pt-2">
        <button
          type="button"
          disabled={!prev}
          onClick={() => prev && onMove(prev)}
          className="grid size-7 place-items-center rounded text-ink-3 hover:bg-surface-2 hover:text-ink disabled:invisible"
          aria-label={prev ? `Move “${t.title}” to ${BID_STATUS[prev].label}` : undefined}
          title={prev ? `Move to ${BID_STATUS[prev].label}` : undefined}
        >
          <ChevronLeft className="size-4" aria-hidden="true" />
        </button>
        <select
          value={b.status}
          onChange={(e) => onMove(e.target.value as BidStatus)}
          className="h-7 min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 text-xs text-ink-2 hover:border-line focus:border-signal focus:outline-none"
          aria-label={`Status of “${t.title}”`}
        >
          {BID_STATUSES.map((s) => (
            <option key={s} value={s}>
              {BID_STATUS[s].label}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={!next}
          onClick={() => next && onMove(next)}
          className="grid size-7 place-items-center rounded text-ink-3 hover:bg-surface-2 hover:text-ink disabled:invisible"
          aria-label={next ? `Move “${t.title}” to ${BID_STATUS[next].label}` : undefined}
          title={next ? `Move to ${BID_STATUS[next].label}` : undefined}
        >
          <ChevronRight className="size-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={() => setEditing((x) => !x)}
          aria-expanded={editing}
          className="grid size-7 place-items-center rounded text-ink-3 hover:bg-surface-2 hover:text-ink"
          aria-label={`Edit “${t.title}”`}
          title="Owner, bid amount, notes"
        >
          <SlidersHorizontal className="size-3.5" aria-hidden="true" />
        </button>
      </div>
      {editing && <BidEditor b={b} onDone={() => setEditing(false)} />}
    </li>
  );
}

function Column({ status, bids, onMove, onDrop }: { status: BidStatus; bids: BidTrack[]; onMove: (b: BidTrack, s: BidStatus) => void; onDrop: (id: number) => void }) {
  const [over, setOver] = useState(false);
  const meta = BID_STATUS[status];
  const accepts = (e: DragEvent) => e.dataTransfer.types.includes(DRAG_TYPE);
  return (
    <section
      aria-label={meta.label}
      onDragOver={(e) => {
        if (!accepts(e)) return;
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        setOver(false);
        const id = Number(e.dataTransfer.getData(DRAG_TYPE));
        if (id) onDrop(id);
      }}
      className={cx("flex min-h-64 flex-col rounded-lg border bg-surface-2/50 transition-colors", over ? "border-signal bg-signal-soft/50" : "border-line")}
    >
      <header className="flex items-center justify-between gap-2 border-b border-line px-3 py-2.5">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-sm font-medium text-ink">
            <span
              className={cx(
                "size-1.5 rounded-full",
                meta.tone === "good" ? "bg-good" : meta.tone === "critical" ? "bg-critical" : meta.tone === "signal" ? "bg-signal" : "bg-line-strong",
              )}
              aria-hidden="true"
            />
            {meta.label}
          </h2>
          <p className="mt-0.5 truncate text-[11px] text-ink-3">{meta.hint}</p>
        </div>
        <span className="num text-xs text-ink-3">{bids.length}</span>
      </header>
      <ul className="flex-1 space-y-2 p-2">
        {bids.map((b) => (
          <BidCard key={b.id} b={b} onMove={(s) => onMove(b, s)} />
        ))}
      </ul>
    </section>
  );
}

function Summary() {
  const s = usePipelineSummary();
  const d = s.data;
  const active = d ? ACTIVE_STATUSES.concat("submitted").reduce((n, k) => n + (d.by_status[k] ?? 0), 0) : undefined;
  const value = d?.value_inr_in_play;
  return (
    <Card className="mt-8 grid gap-px overflow-hidden bg-line lg:grid-cols-[1fr_1.4fr]">
      <dl className="grid grid-cols-3 gap-px bg-line">
        <Stat
          className="bg-surface px-4 py-4"
          label="Value in play"
          value={d ? (Number(value) > 0 ? formatInr(value, { short: true }) : "—") : <Skeleton className="h-7 w-20" />}
          hint="across open bids"
        />
        <Stat className="bg-surface px-4 py-4" label="Active bids" value={active !== undefined ? formatCount(active) : <Skeleton className="h-7 w-10" />} hint="watching to submitted" />
        <Stat className="bg-surface px-4 py-4" label="Won" value={d ? formatCount(d.by_status.won ?? 0) : <Skeleton className="h-7 w-10" />} hint="awarded to you" />
      </dl>
      <div className="bg-surface px-4 py-4">
        <p className="label">
          Closing in 7 days{d && d.closing_soon.length > 0 && <span className="num ml-1.5 text-critical">{d.closing_soon.length}</span>}
        </p>
        {!d ? (
          <Skeleton className="mt-3 h-12 w-full" />
        ) : d.closing_soon.length === 0 ? (
          <p className="mt-2 text-sm text-ink-3">Nothing you're preparing closes soon.</p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {d.closing_soon.slice(0, 3).map((b) => {
              const due = countdown(b.tender.closes_at);
              return (
                <li key={b.id} className="flex items-baseline justify-between gap-3 text-sm">
                  <Link to={`/tenders/${b.tender.id}`} className="min-w-0 truncate text-ink hover:underline">
                    {b.tender.title}
                  </Link>
                  <span className={cx("num shrink-0 text-xs", due.urgent ? "text-critical" : "text-ink-2")}>{due.text}</span>
                </li>
              );
            })}
            {d.closing_soon.length > 3 && <li className="text-xs text-ink-3">and {d.closing_soon.length - 3} more</li>}
          </ul>
        )}
      </div>
    </Card>
  );
}

function Board() {
  const q = usePipeline();
  const update = useUpdateTrack();
  const [filter, setFilter] = useState("");
  const [announce, setAnnounce] = useState("");
  useEffect(() => {
    if (!announce) return;
    const t = setTimeout(() => setAnnounce(""), 3000);
    return () => clearTimeout(t);
  }, [announce]);

  const move = (b: BidTrack, status: BidStatus) => {
    if (b.status === status) return;
    update.mutate({ id: b.id, patch: { status } });
    setAnnounce(`Moved “${b.tender.title}” to ${BID_STATUS[status].label}.`);
  };

  if (q.isLoading) return <Skeleton className="mt-8 h-96 w-full rounded-lg" />;
  if (q.isError)
    return (
      <div className="mt-8">
        <EmptyState icon={<ClipboardList className="size-5" />} title="Couldn't load your pipeline">
          {errorMessage(q.error)}
        </EmptyState>
      </div>
    );
  const all = q.data ?? [];
  if (all.length === 0) {
    return (
      <div className="mt-8">
        <EmptyState icon={<ClipboardList className="size-5" />} title="Nothing in your pipeline yet">
          Press <Tag className="mx-0.5 h-5">Track</Tag> on any tender and it lands here under Watching. Then move it along as you prepare, submit and hear back.
          <div className="mt-5">
            <ButtonLink to="/tenders" variant="primary">
              <Search className="size-4" aria-hidden="true" /> Explore tenders
            </ButtonLink>
          </div>
        </EmptyState>
      </div>
    );
  }
  const needle = filter.trim().toLowerCase();
  const shown = needle
    ? all.filter((b) => [b.tender.title, b.tender.buyer?.canonical_name ?? b.tender.buyer_raw, b.tender.source_tender_id, b.notes].join(" ").toLowerCase().includes(needle))
    : all;
  // Most urgent first within a column.
  const byClosing = (a: BidTrack, b: BidTrack) => new Date(a.tender.closes_at).getTime() - new Date(b.tender.closes_at).getTime();

  return (
    <>
      <Summary />
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" aria-hidden="true" />
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter bids" aria-label="Filter bids" className={cx(inputClass, "h-9 pl-9")} />
        </div>
        <p className="text-xs text-ink-3">Drag a card, or use its arrows or status menu to move it.</p>
      </div>
      <p className="sr-only" role="status" aria-live="polite">
        {announce}
      </p>
      <div className="-mx-4 mt-4 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0">
        <div className="grid min-w-max auto-cols-[232px] grid-flow-col gap-3 xl:min-w-0 xl:auto-cols-[minmax(232px,1fr)]">
          {BID_STATUSES.map((s) => (
            <Column
              key={s}
              status={s}
              bids={shown.filter((b) => b.status === s).sort(byClosing)}
              onMove={move}
              onDrop={(id) => {
                const b = all.find((x) => x.id === id);
                if (b) move(b, s);
              }}
            />
          ))}
        </div>
      </div>
    </>
  );
}

export default function Pipeline() {
  const signedIn = useSignedIn();
  const [calendar, setCalendar] = useState(false);
  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageHeader
        kicker="Pipeline"
        title="Bid pipeline"
        actions={
          <>
            {signedIn && (
              <Button onClick={() => setCalendar(true)}>
                <CalendarDays className="size-4" aria-hidden="true" /> Add deadlines to calendar
              </Button>
            )}
            <ButtonLink to="/tenders">
              <Search className="size-4" aria-hidden="true" /> Find tenders
            </ButtonLink>
          </>
        }
      >
        Every tender your team is working on, from first look to award. Owners get an email when a tracked bid is three days from closing and not yet submitted.
      </PageHeader>
      <SignInGate title="Sign in to manage your bids" pitch="Track tenders from Explore, move them from watching to submitted, and share the board with your team.">
        <Board />
      </SignInGate>
      <Dialog open={calendar} onClose={() => setCalendar(false)} title="Deadlines in your calendar">
        <CalendarFeed />
      </Dialog>
    </div>
  );
}
