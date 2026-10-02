import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Bell, ChevronLeft, ChevronRight, Info, SearchX, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { TenderCard, TenderCardSkeleton } from "../components/TenderCard";
import { Button, cx, EmptyState, inputClass } from "../components/ui";
import { api, type Bucket, type Filters, filtersFromParams, filtersToParams, PAGE_SIZE, VALUE_RANGES } from "../lib/api";
import { formatCount } from "../lib/format";
import { SectorIcon, sectorMeta } from "../lib/sectors";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function FacetList({
  title,
  buckets,
  active,
  onPick,
  render,
  searchable,
}: {
  title: string;
  buckets: Bucket[] | undefined;
  active: string;
  onPick: (k: string) => void;
  render?: (key: string) => React.ReactNode;
  searchable?: boolean;
}) {
  const [all, setAll] = useState(false);
  const [filter, setFilter] = useState("");
  const list = (buckets ?? []).filter((b) => !filter || b.key.toLowerCase().includes(filter.toLowerCase()));
  const shown = all || filter ? list : list.slice(0, 7);
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold tracking-wider text-ink-3 uppercase">{title}</h3>
      {searchable && (buckets?.length ?? 0) > 8 && (
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={`Filter ${title.toLowerCase()}`} className={cx(inputClass, "mb-2 h-9")} aria-label={`Filter ${title}`} />
      )}
      <ul className="space-y-0.5">
        {shown.map((b) => (
          <li key={b.key}>
            <button
              onClick={() => onPick(b.key === active ? "" : b.key)}
              aria-pressed={b.key === active}
              className={cx(
                "flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors",
                b.key === active ? "bg-brand-soft font-semibold text-brand" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
              )}
            >
              <span className="flex min-w-0 items-center gap-2 truncate">{render ? render(b.key) : b.key}</span>
              <span className="shrink-0 text-xs tabular-nums text-ink-3">{formatCount(b.count)}</span>
            </button>
          </li>
        ))}
      </ul>
      {!filter && list.length > 7 && (
        <button onClick={() => setAll((a) => !a)} className="mt-1 px-2.5 text-sm font-medium text-brand hover:underline">
          {all ? "Show fewer" : `Show all ${list.length}`}
        </button>
      )}
    </section>
  );
}

function FilterPanel({ f, set, facets }: { f: Filters; set: (p: Partial<Filters>) => void; facets?: Record<string, Bucket[]> }) {
  const [pin, setPin] = useState(f.pin);
  useEffect(() => setPin(f.pin), [f.pin]);
  return (
    <div className="space-y-7">
      <FacetList
        title="Sector"
        buckets={facets?.sector}
        active={f.sector}
        onPick={(sector) => set({ sector })}
        render={(k) => (
          <>
            <SectorIcon slug={k} className="size-4 shrink-0" />
            <span className="truncate">{sectorMeta(k).label}</span>
          </>
        )}
      />
      <FacetList title="State" buckets={facets?.state} active={f.state} onPick={(state) => set({ state })} searchable />
      <section>
        <h3 className="mb-2 text-xs font-semibold tracking-wider text-ink-3 uppercase">PIN area</h3>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            set({ pin: pin.trim() });
          }}
        >
          <input
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))}
            inputMode="numeric"
            placeholder="e.g. 490"
            className={cx(inputClass, "h-9")}
            aria-label="PIN code prefix"
          />
          <Button size="sm" type="submit" className="h-9">
            Apply
          </Button>
        </form>
        <p className="mt-1.5 text-xs text-ink-3">First digits of a PIN code. 490 is Bhilai/Durg, 492 Raipur.</p>
      </section>
      <FacetList
        title="Tender value"
        buckets={Object.keys(VALUE_RANGES).map((k) => facets?.value_range?.find((b) => b.key === k) ?? { key: k, count: 0 })}
        active={f.value}
        onPick={(value) => set({ value })}
        render={(k) => VALUE_RANGES[k]?.label ?? k}
      />
      <FacetList title="Type" buckets={facets?.category} active={f.category} onPick={(category) => set({ category })} />
      <label className="flex items-center gap-2 px-1 text-sm text-ink-2">
        <input type="checkbox" checked={f.includeClosed} onChange={(e) => set({ includeClosed: e.target.checked })} className="size-4 accent-[var(--brand)]" />
        Include closed tenders
      </label>
    </div>
  );
}

export default function Explore() {
  const [params, setParams] = useSearchParams();
  const f = useMemo(() => filtersFromParams(params), [params]);
  const [text, setText] = useState(f.q);
  const debounced = useDebounced(text, 350);
  const [drawer, setDrawer] = useState(false);

  const set = (patch: Partial<Filters>) => {
    const next = { ...f, page: 1, ...patch };
    setParams(filtersToParams(next), { replace: !("page" in patch) });
  };

  useEffect(() => setText(f.q), [f.q]);
  useEffect(() => {
    if (debounced !== f.q) set({ q: debounced });
  }, [debounced]);

  const q = useQuery({ queryKey: ["tenders", f], queryFn: ({ signal }) => api.tenders(f, signal), placeholderData: keepPreviousData });
  const buyer = useQuery({ queryKey: ["buyer", f.buyer], queryFn: () => api.buyer(Number(f.buyer)), enabled: !!f.buyer });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.count / PAGE_SIZE)) : 1;

  const chips: { label: React.ReactNode; clear: Partial<Filters> }[] = [];
  if (f.sector) chips.push({ label: sectorMeta(f.sector).label, clear: { sector: "" } });
  if (f.state) chips.push({ label: f.state, clear: { state: "" } });
  if (f.pin) chips.push({ label: `PIN ${f.pin}xxx`, clear: { pin: "" } });
  if (f.value) chips.push({ label: VALUE_RANGES[f.value]?.label ?? f.value, clear: { value: "" } });
  if (f.category) chips.push({ label: f.category, clear: { category: "" } });
  if (f.buyer) chips.push({ label: buyer.data?.canonical_name ?? "Buyer", clear: { buyer: "" } });
  if (f.includeClosed) chips.push({ label: "Including closed", clear: { includeClosed: false } });

  const alertHref = `/alerts?${new URLSearchParams({
    ...(f.state ? { state: f.state } : {}),
    ...(f.sector ? { sector: f.sector } : {}),
    ...(f.pin ? { pin: f.pin } : {}),
    ...(f.q ? { keywords: f.q } : {}),
  })}`;

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <div className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Explore tenders</h1>
        <p className="mt-1 text-ink-2">Search titles, buyers, locations or a tender ID. Typos and partial words are fine.</p>
      </div>

      <div className="sticky top-16 z-20 -mx-4 mb-6 border-b border-line bg-bg/90 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-2xl sm:border sm:bg-surface sm:px-3">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            type="search"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Search tenders…"
            className={cx(inputClass, "flex-1 text-base")}
            aria-label="Search tenders"
          />
          <div className="flex gap-2">
            <select
              value={f.sort}
              onChange={(e) => set({ sort: e.target.value as Filters["sort"] })}
              className={cx(inputClass, "w-auto pr-8")}
              aria-label="Sort by"
            >
              <option value="relevance">{f.q ? "Best match" : "Closing soonest"}</option>
              <option value="closing">Closing soonest</option>
              <option value="newest">Newest first</option>
              <option value="value">Highest value</option>
            </select>
            <Button className="h-11 lg:hidden" onClick={() => setDrawer(true)}>
              <SlidersHorizontal className="size-4" /> Filters{chips.length ? ` (${chips.length})` : ""}
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-8 lg:grid-cols-[260px_1fr]">
        <aside className="hidden lg:block" aria-label="Filters">
          <FilterPanel f={f} set={set} facets={q.data?.facets} />
        </aside>

        <div>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <p className="mr-2 text-sm text-ink-2" aria-live="polite">
              {q.data ? (
                <>
                  <span className="font-semibold text-ink">{formatCount(q.data.count)}</span> {f.includeClosed ? "tenders" : "open tenders"}
                </>
              ) : (
                "Loading…"
              )}
            </p>
            {chips.map((c, i) => (
              <button
                key={i}
                onClick={() => set(c.clear)}
                className="inline-flex items-center gap-1 rounded-full border border-line bg-surface py-1 pr-2 pl-3 text-sm text-ink hover:bg-surface-2"
              >
                {c.label}
                <X className="size-3.5 text-ink-3" aria-label="Remove filter" />
              </button>
            ))}
            {chips.length > 1 && (
              <button onClick={() => (setText(""), setParams(new URLSearchParams()))} className="text-sm font-medium text-brand hover:underline">
                Clear all
              </button>
            )}
            <Link to={alertHref} className="ml-auto inline-flex items-center gap-1.5 text-sm font-semibold text-brand hover:underline">
              <Bell className="size-4" /> Alert me about these
            </Link>
          </div>

          {q.data?.relaxed && (
            <p className="mb-4 flex items-center gap-2 rounded-xl bg-brand-soft px-4 py-3 text-sm text-brand">
              <Info className="size-4 shrink-0" /> No tender matched every word, so these match some of them.
            </p>
          )}
          {buyer.data && buyer.data.aliases.length > 1 && (
            <p className="mb-4 rounded-xl border border-line bg-surface px-4 py-3 text-sm text-ink-2">
              Showing all {buyer.data.aliases.length} spellings of <span className="font-semibold text-ink">{buyer.data.canonical_name}</span>.
            </p>
          )}

          {q.isError ? (
            <EmptyState icon={<SearchX className="size-6" />} title="Couldn't load tenders">
              Check your connection and try again.
            </EmptyState>
          ) : q.isLoading ? (
            <div className="grid gap-3">{Array.from({ length: 5 }, (_, i) => <TenderCardSkeleton key={i} />)}</div>
          ) : q.data?.count === 0 ? (
            <EmptyState icon={<SearchX className="size-6" />} title="No tenders match">
              Try fewer filters or different words. You can also{" "}
              <Link to={alertHref} className="font-medium text-brand hover:underline">
                create an alert
              </Link>{" "}
              and we'll email you when one opens.
            </EmptyState>
          ) : (
            <div className={cx("grid gap-3 transition-opacity", q.isPlaceholderData && "opacity-60")}>
              {q.data?.results.map((t) => <TenderCard key={t.id} t={t} />)}
            </div>
          )}

          {pages > 1 && (
            <nav className="mt-8 flex items-center justify-center gap-3 text-sm" aria-label="Pages">
              <Button disabled={f.page <= 1} onClick={() => set({ page: f.page - 1 })}>
                <ChevronLeft className="size-4" /> Previous
              </Button>
              <span className="text-ink-2 tabular-nums">
                Page {f.page} of {formatCount(pages)}
              </span>
              <Button disabled={f.page >= pages} onClick={() => set({ page: f.page + 1 })}>
                Next <ChevronRight className="size-4" />
              </Button>
            </nav>
          )}
        </div>
      </div>

      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Filters">
          <div className="absolute inset-0 bg-black/50" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 right-0 flex w-[min(88vw,360px)] flex-col bg-bg">
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <h2 className="font-semibold text-ink">Filters</h2>
              <button onClick={() => setDrawer(false)} aria-label="Close filters" className="rounded-full p-1 text-ink-3 hover:bg-surface-2">
                <X className="size-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-5">
              <FilterPanel f={f} set={set} facets={q.data?.facets} />
            </div>
            <div className="border-t border-line p-4">
              <Button variant="primary" className="w-full" onClick={() => setDrawer(false)}>
                Show {formatCount(q.data?.count)} tenders
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
