import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { Bell, ChevronLeft, ChevronRight, Download, Info, Search, SearchX, SlidersHorizontal, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { RecommendedList } from "../components/Recommended";
import { SignInDialog } from "../components/SignIn";
import { TenderListHeader, TenderRow, TenderRowSkeleton } from "../components/TenderCard";
import { Button, ButtonLink, cx, EmptyState, inputBase, inputClass, PageHeader } from "../components/ui";
import { api, type Bucket, type CsvExport, errorMessage, type Filters, filtersFromParams, filtersToParams, PAGE_SIZE, quotaExceeded, VALUE_RANGES } from "../lib/api";
import { formatCount } from "../lib/format";
import { useSignedIn } from "../lib/queries";
import { useToast } from "../lib/toast";
import { SectorIcon, sectorMeta } from "../lib/sectors";

const SORT_LABELS: Record<Filters["sort"], string> = {
  relevance: "best match",
  closing: "closing soonest",
  newest: "newest first",
  value: "highest value",
};

const pad = (n: number) => String(n).padStart(2, "0");
const smallInput = `h-8 w-full ${inputBase}`;

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
    <section className="py-5 first:pt-0">
      <div className="mb-2.5 flex items-center justify-between">
        <h3 className="label">{title}</h3>
        {active && (
          <button onClick={() => onPick("")} className="text-xs text-ink-3 hover:text-ink">
            Reset
          </button>
        )}
      </div>
      {searchable && (buckets?.length ?? 0) > 8 && (
        <div className="relative mb-2">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-3" aria-hidden="true" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={`Filter ${title.toLowerCase()}`}
            className={cx(smallInput, "pl-8 text-[13px]")}
            aria-label={`Filter ${title}`}
          />
        </div>
      )}
      <ul className="-mx-2 space-y-px">
        {shown.map((b) => {
          const on = b.key === active;
          return (
            <li key={b.key}>
              <button
                onClick={() => onPick(on ? "" : b.key)}
                aria-pressed={on}
                className={cx(
                  "relative flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors",
                  on
                    ? "bg-surface-2 font-medium text-ink before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-signal"
                    : "text-ink-2 hover:bg-surface-2/60 hover:text-ink",
                )}
              >
                <span className="flex min-w-0 items-center gap-2 truncate">{render ? render(b.key) : b.key}</span>
                <span className={cx("num shrink-0 text-xs", on ? "text-ink-2" : "text-ink-3")}>{formatCount(b.count)}</span>
              </button>
            </li>
          );
        })}
      </ul>
      {!filter && list.length > 7 && (
        <button onClick={() => setAll((a) => !a)} className="mt-1.5 text-xs font-medium text-ink-3 hover:text-ink">
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
    <div className="divide-y divide-line">
      <FacetList
        title="Sector"
        buckets={facets?.sector}
        active={f.sector}
        onPick={(sector) => set({ sector })}
        render={(k) => (
          <>
            <SectorIcon slug={k} className="size-3.5 shrink-0 text-ink-3" />
            <span className="truncate">{sectorMeta(k).label}</span>
          </>
        )}
      />
      <FacetList title="State" buckets={facets?.state} active={f.state} onPick={(state) => set({ state })} searchable />
      <section className="py-5">
        <div className="mb-2.5 flex items-center justify-between">
          <h3 className="label">PIN area</h3>
          {f.pin && (
            <button onClick={() => set({ pin: "" })} className="text-xs text-ink-3 hover:text-ink">
              Reset
            </button>
          )}
        </div>
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
            className={cx(smallInput, "num text-[13px]")}
            aria-label="PIN code prefix"
          />
          <Button size="sm" type="submit">
            Apply
          </Button>
        </form>
        <p className="mt-2 text-xs text-ink-3">First digits of a PIN code. 490 is Bhilai/Durg, 492 Raipur.</p>
      </section>
      <FacetList
        title="Tender value"
        buckets={Object.keys(VALUE_RANGES).map((k) => facets?.value_range?.find((b) => b.key === k) ?? { key: k, count: 0 })}
        active={f.value}
        onPick={(value) => set({ value })}
        render={(k) => VALUE_RANGES[k]?.label ?? k}
      />
      <FacetList title="Type" buckets={facets?.category} active={f.category} onPick={(category) => set({ category })} />
      <div className="pt-5">
        <label className="flex cursor-pointer items-center gap-2.5 rounded-md border border-line px-3 py-2.5 text-[13px] text-ink-2 transition-colors hover:border-line-strong hover:text-ink">
          <input
            type="checkbox"
            checked={f.includeClosed}
            onChange={(e) => set({ includeClosed: e.target.checked })}
            className="size-4 accent-[var(--signal)]"
          />
          Include closed tenders
        </label>
      </div>
    </div>
  );
}

function Notice({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "signal" | "neutral" }) {
  return (
    <p className={cx("mb-4 flex items-start gap-2.5 border-l-2 py-1 pl-3 text-sm text-ink-2", tone === "signal" ? "border-signal" : "border-line-strong")}>
      {tone === "signal" && <Info className="mt-0.5 size-4 shrink-0 text-signal-text" aria-hidden="true" />}
      <span>{children}</span>
    </p>
  );
}

type View = "all" | "recommended";

function ViewTabs({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  const tabs: { v: View; label: React.ReactNode }[] = [
    { v: "all", label: "All tenders" },
    {
      v: "recommended",
      label: (
        <>
          <Sparkles className="size-3.5 text-signal-text" aria-hidden="true" /> Recommended for you
        </>
      ),
    },
  ];
  return (
    <div
      role="tablist"
      aria-label="Which tenders"
      className="mt-6 flex gap-1 border-b border-line"
      onKeyDown={(e) => {
        // Arrow keys move between tabs (WAI-ARIA tabs pattern); Tab leaves the list.
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        const next = tabs[(tabs.findIndex((t) => t.v === view) + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length].v;
        onChange(next);
        requestAnimationFrame(() => document.getElementById(`view-tab-${next}`)?.focus());
      }}
    >
      {tabs.map((t) => (
        <button
          key={t.v}
          id={`view-tab-${t.v}`}
          type="button"
          role="tab"
          aria-selected={view === t.v}
          tabIndex={view === t.v ? 0 : -1}
          onClick={() => onChange(t.v)}
          className={cx(
            "-mb-px inline-flex items-center gap-1.5 border-b px-3 py-2.5 text-sm transition-colors",
            view === t.v ? "border-signal font-medium text-ink" : "border-transparent text-ink-3 hover:text-ink",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** CSV of the current search (plan feature "export"). A 402 opens the upgrade dialog. */
function useCsvExport(onTruncated: (r: CsvExport | null) => void) {
  const toast = useToast();
  return useMutation({
    mutationFn: (f: Filters) => api.exports.downloadCsv(f),
    onSuccess: (r) => {
      onTruncated(r.truncated ? r : null);
      toast("success", r.truncated ? `Exported the first ${formatCount(r.rows)} of ${formatCount(r.total)} tenders` : `Exported ${formatCount(r.total)} tenders`);
    },
    onError: (e) => quotaExceeded(e) || toast("error", errorMessage(e, "Couldn't export the tenders")),
  });
}

export default function Explore() {
  const [params, setParams] = useSearchParams();
  const f = useMemo(() => filtersFromParams(params), [params]);
  const signedIn = useSignedIn();
  const view: View = signedIn && params.get("view") === "recommended" ? "recommended" : "all";
  const [truncated, setTruncated] = useState<CsvExport | null>(null);
  const [signIn, setSignIn] = useState(false);
  const csv = useCsvExport(setTruncated);
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
  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawer]);

  const q = useQuery({ queryKey: ["tenders", f], queryFn: ({ signal }) => api.tenders(f, signal), placeholderData: keepPreviousData, enabled: view === "all" });
  const switchView = (v: View) => setParams(v === "recommended" ? new URLSearchParams({ view: "recommended" }) : filtersToParams({ ...f, page: 1 }));
  const buyer = useQuery({ queryKey: ["buyer", f.buyer], queryFn: () => api.buyer(Number(f.buyer)), enabled: !!f.buyer });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.count / PAGE_SIZE)) : 1;

  const chips: { label: React.ReactNode; clear: Partial<Filters> }[] = [];
  if (f.sector) chips.push({ label: sectorMeta(f.sector).label, clear: { sector: "" } });
  if (f.state) chips.push({ label: f.state, clear: { state: "" } });
  if (f.pin) chips.push({ label: <span className="num">PIN {f.pin}xxx</span>, clear: { pin: "" } });
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
  const sortLabel = f.sort === "relevance" && !f.q ? SORT_LABELS.closing : SORT_LABELS[f.sort];

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageHeader
        kicker="Index"
        title="Tenders"
        actions={
          <>
            {view === "all" && (
              <>
                <div className="mr-3 text-right" aria-live="polite">
                  <p className="label">{f.includeClosed ? "Results" : "Open now"}</p>
                  <p className="num mt-1 text-2xl font-medium text-ink">{q.data ? formatCount(q.data.count) : "—"}</p>
                </div>
                <Button onClick={() => (signedIn ? csv.mutate(f) : setSignIn(true))} disabled={csv.isPending} title="Download these results as a spreadsheet (CSV)">
                  <Download className="size-4" aria-hidden="true" /> {csv.isPending ? "Exporting…" : "Export CSV"}
                </Button>
                <ButtonLink to={alertHref}>
                  <Bell className="size-4" aria-hidden="true" /> Alert me about these
                </ButtonLink>
              </>
            )}
          </>
        }
      >
        Search titles, buyers, locations or a tender ID. Typos and partial words are fine.
      </PageHeader>
      <SignInDialog open={signIn} onClose={() => setSignIn(false)} title="Sign in to export tenders">
        Exports come with the paid plans. Sign in to see yours.
      </SignInDialog>
      {signedIn && <ViewTabs view={view} onChange={switchView} />}
      {view === "recommended" ? (
        <div className="mt-6">
          <RecommendedList page={f.page} onPage={(page) => setParams(new URLSearchParams({ view: "recommended", ...(page > 1 ? { page: String(page) } : {}) }))} />
        </div>
      ) : (
      <>

      <div className="sticky top-14 z-20 -mx-4 border-b border-line bg-bg/90 px-4 py-3 backdrop-blur-md sm:mx-0 sm:px-0">
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" aria-hidden="true" />
            <input
              type="search"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Road repair, CCTV, AIIMS, 2026_EIL_…"
              className={cx(inputClass, "pr-9 pl-9 text-[15px] [&::-webkit-search-cancel-button]:hidden")}
              aria-label="Search tenders"
            />
            {text && (
              <button
                type="button"
                onClick={() => setText("")}
                className="absolute top-1/2 right-2 grid size-6 -translate-y-1/2 place-items-center rounded text-ink-3 hover:bg-surface-2 hover:text-ink"
                aria-label="Clear search"
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>
          <div className="flex gap-2">
            <label className="flex flex-1 items-center gap-2 sm:flex-none">
              <span className="label hidden shrink-0 sm:inline">Sort</span>
              <select
                value={f.sort}
                onChange={(e) => set({ sort: e.target.value as Filters["sort"] })}
                className={cx(inputClass, "w-full pr-8 sm:w-auto")}
                aria-label="Sort by"
              >
                <option value="relevance">{f.q ? "Best match" : "Closing soonest"}</option>
                <option value="closing">Closing soonest</option>
                <option value="newest">Newest first</option>
                <option value="value">Highest value</option>
              </select>
            </label>
            <Button className="lg:hidden" onClick={() => setDrawer(true)}>
              <SlidersHorizontal className="size-4" aria-hidden="true" /> Filters
              {chips.length > 0 && <span className="num rounded bg-signal px-1.5 text-xs leading-5 text-signal-ink">{chips.length}</span>}
            </Button>
          </div>
        </div>
      </div>

      <div className="mt-8 grid gap-10 lg:grid-cols-[240px_1fr]">
        <aside className="hidden lg:block" aria-label="Filters">
          <FilterPanel f={f} set={set} facets={q.data?.facets} />
        </aside>

        <div className="min-w-0">
          <div className="mb-4 flex min-h-6 flex-wrap items-center gap-2">
            {chips.length ? (
              <>
                <span className="label mr-1">Filters</span>
                {chips.map((c, i) => (
                  <button key={i} onClick={() => set(c.clear)} className="tag hover:border-line-strong hover:text-ink">
                    {c.label}
                    <X className="size-3 text-ink-3" aria-label="Remove filter" />
                  </button>
                ))}
                {chips.length > 1 && (
                  <button
                    onClick={() => (setText(""), setParams(new URLSearchParams()))}
                    className="ml-1 text-xs font-medium text-ink-3 underline decoration-line-strong underline-offset-4 hover:text-ink"
                  >
                    Clear all
                  </button>
                )}
              </>
            ) : (
              <p className="text-sm text-ink-3">
                All {f.includeClosed ? "tenders" : "open tenders"}, sorted by {sortLabel}.
              </p>
            )}
          </div>

          {truncated && (
            <Notice tone="signal">
              The export holds the first {formatCount(truncated.rows)} of {formatCount(truncated.total)} matching tenders. Narrow the filters to export the rest.
            </Notice>
          )}
          {q.data?.relaxed && <Notice tone="signal">No tender matched every word, so these match some of them.</Notice>}
          {buyer.data && buyer.data.aliases.length > 1 && (
            <Notice>
              Showing all {buyer.data.aliases.length} spellings of <span className="font-medium text-ink">{buyer.data.canonical_name}</span>.
            </Notice>
          )}

          {q.isError ? (
            <EmptyState icon={<SearchX className="size-5" />} title="Couldn't load tenders">
              Check your connection and try again.
            </EmptyState>
          ) : q.data?.count === 0 ? (
            <EmptyState icon={<SearchX className="size-5" />} title="No tenders match">
              Try fewer filters or different words. You can also{" "}
              <Link to={alertHref} className="font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-signal">
                create an alert
              </Link>{" "}
              and we'll email you when one opens.
            </EmptyState>
          ) : (
            <div className={cx("panel overflow-hidden transition-opacity", q.isPlaceholderData && "opacity-60")}>
              <TenderListHeader />
              {q.isLoading ? Array.from({ length: 6 }, (_, i) => <TenderRowSkeleton key={i} />) : q.data?.results.map((t) => <TenderRow key={t.id} t={t} />)}
            </div>
          )}

          {pages > 1 && (
            <nav className="mt-6 flex items-center justify-between gap-3" aria-label="Pages">
              <Button size="sm" disabled={f.page <= 1} onClick={() => set({ page: f.page - 1 })}>
                <ChevronLeft className="size-4" aria-hidden="true" /> Previous
              </Button>
              <p className="num text-sm text-ink-3">
                Page <span className="text-ink">{pad(f.page)}</span> / {pad(pages)}
              </p>
              <Button size="sm" disabled={f.page >= pages} onClick={() => set({ page: f.page + 1 })}>
                Next <ChevronRight className="size-4" aria-hidden="true" />
              </Button>
            </nav>
          )}
        </div>
      </div>

      </>
      )}

      {drawer && view === "all" && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Filters">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-[2px]" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 right-0 flex w-[min(88vw,360px)] flex-col border-l border-line bg-bg">
            <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
              <div>
                <h2 className="text-[15px] font-semibold text-ink">Filters</h2>
                <p className="num text-xs text-ink-3">{formatCount(q.data?.count)} matching</p>
              </div>
              <button onClick={() => setDrawer(false)} aria-label="Close filters" className="grid size-8 place-items-center rounded-md text-ink-3 hover:bg-surface-2 hover:text-ink">
                <X className="size-4" />
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
