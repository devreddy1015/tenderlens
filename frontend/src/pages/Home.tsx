import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ArrowUpRight, Search } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link, useNavigate } from "react-router";
import { IndiaMap } from "../components/IndiaMap";
import { InterfaceLines } from "../components/InterfaceLines";
import { StatePanel, TopStates } from "../components/StatePanel";
import { TenderListHeader, TenderRow, TenderRowSkeleton } from "../components/TenderCard";
import { Button, ButtonLink, cx, SectionHeading, Skeleton, Stat, Tag } from "../components/ui";
import { type AlertCriteria, api, DEFAULT_FILTERS, type SectorStat } from "../lib/api";
import { formatCount, formatInr, timeAgo } from "../lib/format";
import { SectorIcon, sectorMeta } from "../lib/sectors";

const QUICK = ["roads", "buildings", "electrical", "it", "security", "health"];

/** A plain ink link with a hairline underline that turns amber on hover. */
const textLink =
  "inline-flex items-center gap-1 text-sm font-medium text-ink underline decoration-line-strong underline-offset-4 transition-colors hover:decoration-signal";

/** "4d", "3h", "12m": the time column of the feed. */
function shortAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  return hours < 24 ? `${hours}h` : `${Math.round(hours / 24)}d`;
}

function Section({ children, rule = true, className }: { children: ReactNode; rule?: boolean; className?: string }) {
  return (
    <section className={cx(rule && "border-t border-line", className)}>
      <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 sm:py-20">{children}</div>
    </section>
  );
}

// --- Hero ------------------------------------------------------------------------------

function Hero() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  return (
    <section className="relative overflow-hidden">
      <div className="grid-paper pointer-events-none absolute inset-0 [mask-image:radial-gradient(90%_75%_at_50%_0%,black,transparent_75%)]" aria-hidden="true" />
      <InterfaceLines className="field-mask-hero [--calm-h:52%] [--calm-w:44%] [--calm-x:27%] [--calm-y:50%]" />
      <div className="relative mx-auto grid max-w-7xl grid-cols-1 gap-12 px-4 pt-16 pb-16 sm:px-6 sm:pt-24 sm:pb-24 lg:grid-cols-[1.3fr_1fr] lg:items-center lg:gap-16">
        <div>
          <p className="eyebrow">Public procurement index · India</p>
          <h1 className="mt-6 text-[2.5rem] leading-[1.04] font-semibold tracking-[-0.035em] sm:text-6xl lg:text-[3.6rem]">
            <span className="block text-ink">Every open government tender in India.</span>
            <span className="block text-ink-3">Found before it closes.</span>
          </h1>
          <p className="mt-6 max-w-xl text-[17px] leading-relaxed text-ink-2">
            One search across central ministries, PSUs and state portals, mapped by state and PIN area, with an email the hour something new opens.
          </p>

          <form
            role="search"
            className="mt-9 flex max-w-xl items-center gap-2 rounded-lg border border-line-strong bg-surface p-1.5 pl-3.5 shadow-panel transition-colors focus-within:border-signal"
            onSubmit={(e) => {
              e.preventDefault();
              nav(`/tenders${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`);
            }}
          >
            <Search className="size-4 shrink-0 text-ink-3" aria-hidden="true" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Road repair, CCTV, solar plant, AIIMS…"
              className="h-11 min-w-0 flex-1 bg-transparent text-[15px] text-ink placeholder:text-ink-3 focus:outline-none"
              aria-label="Search tenders"
            />
            <Button type="submit" variant="primary" size="lg" className="h-11">
              Search <ArrowRight className="size-4" aria-hidden="true" />
            </Button>
          </form>
          <p className="mt-3 hidden items-center gap-1.5 text-xs text-ink-3 lg:flex">
            Press <kbd className="kbd">/</kbd> to search from any page. Tender IDs and buyer names work too.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-2">
            <span className="label mr-1">Jump to</span>
            {QUICK.map((slug) => (
              <Link key={slug} to={`/tenders?sector=${slug}`} className="tag h-7 px-2.5 transition-colors hover:border-line-strong hover:text-ink">
                <SectorIcon slug={slug} className="size-3.5" />
                {sectorMeta(slug).label}
              </Link>
            ))}
          </div>
        </div>
        <Feed />
      </div>
    </section>
  );
}

/** The newest tenders as a log: relative time, title, state and value. */
function Feed() {
  const q = useQuery({ queryKey: ["newest"], queryFn: () => api.tenders({ ...DEFAULT_FILTERS, sort: "newest" }) });
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  return (
    <aside className="panel ticks hidden bg-surface/90 backdrop-blur-sm lg:block" aria-label="Newly published tenders">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <p className="label flex items-center gap-2.5 text-ink-2">
          <span className="live-dot" aria-hidden="true" />
          Newly published
        </p>
        <Link to="/tenders?sort=newest" className="inline-flex items-center gap-0.5 text-xs text-ink-2 hover:text-ink">
          See newest <ArrowUpRight className="size-3.5" aria-hidden="true" />
        </Link>
      </div>
      <ol className="overflow-hidden">
        {q.isLoading
          ? Array.from({ length: 5 }, (_, i) => (
              <li key={i} className="grid grid-cols-[36px_1fr] gap-3 border-b border-line px-4 py-3.5 last:border-b-0">
                <Skeleton className="h-3 w-6" />
                <div>
                  <Skeleton className="mb-2 h-3.5 w-full" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              </li>
            ))
          : q.data?.results.slice(0, 5).map((t) => (
              <li key={t.id} className="border-b border-line last:border-b-0">
                <Link to={`/tenders/${t.id}`} className="group grid grid-cols-[36px_1fr] gap-3 px-4 py-3.5 transition-colors hover:bg-surface-2/70">
                  <span className="num pt-px text-xs text-ink-3" title={`Published ${timeAgo(t.published_at)}`}>
                    {shortAgo(t.published_at)}
                  </span>
                  <span className="min-w-0">
                    <span className="line-clamp-2 text-[13.5px] leading-snug text-ink group-hover:underline group-hover:decoration-line-strong group-hover:underline-offset-4">
                      {t.title}
                    </span>
                    <span className="mt-1.5 flex items-center gap-1.5 truncate text-xs text-ink-3">
                      <SectorIcon slug={t.sector} className="size-3 shrink-0" />
                      <span className="truncate">{t.state || "India"}</span>
                      <span aria-hidden="true">·</span>
                      <span className={cx("num", t.value_inr && "text-ink-2")}>{formatInr(t.value_inr, { short: true })}</span>
                    </span>
                  </span>
                </Link>
              </li>
            ))}
      </ol>
      <div className="label flex justify-between border-t border-line px-4 py-2.5 text-[10px]">
        <span>Source · CPPP, MP e-tenders</span>
        <span>Crawled {stats.data ? timeAgo(stats.data.last_crawl?.finished) : "…"}</span>
      </div>
    </aside>
  );
}

/** Four headline numbers on a hairline grid, right under the hero. */
function Readout() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  const sectors = useQuery({ queryKey: ["sectors"], queryFn: api.sectors });
  const s = stats.data;
  const totalValue = sectors.data?.reduce((sum, x) => sum + Number(x.value_inr ?? 0), 0);
  const states = s?.by_state.filter((x) => x.state !== "Unknown").length;
  const cells = [
    { label: "Open tenders", value: s && formatCount(s.open_tenders), hint: s && `of ${formatCount(s.total_tenders)} indexed` },
    {
      label: "Closing in 7 days",
      value: s && formatCount(s.closing_this_week),
      hint: s && s.open_tenders > 0 && `${Math.round((s.closing_this_week / s.open_tenders) * 100)}% of open tenders`,
    },
    { label: "Disclosed value", value: totalValue !== undefined && formatInr(totalValue, { short: true }), hint: "sum of published values" },
    { label: "States & UTs", value: states !== undefined && formatCount(states), hint: "with an open tender" },
  ];
  return (
    <section className="border-y border-line bg-surface/60">
      <dl className="mx-auto grid max-w-7xl grid-cols-2 gap-px bg-line sm:grid-cols-4 xl:border-x xl:border-line">
        {cells.map((c) => (
          <Stat
            key={c.label}
            label={c.label}
            value={c.value || <Skeleton className="h-8 w-24" />}
            hint={c.hint || <span className="invisible">–</span>}
            className="bg-bg px-4 py-6 sm:px-6 sm:py-7 [&_dd.num]:text-[24px] [&_dd.num]:leading-none [&_dd.num]:whitespace-nowrap sm:[&_dd.num]:text-[32px]"
          />
        ))}
      </dl>
    </section>
  );
}

// --- 01 Map ----------------------------------------------------------------------------

function MapSection() {
  const map = useQuery({ queryKey: ["map", ""], queryFn: () => api.map() });
  const [selected, setSelected] = useState<string>();
  const current = selected ?? map.data?.[0]?.state;
  const stat = map.data?.find((s) => s.state === current);
  return (
    <Section rule={false}>
      <SectionHeading
        index="01"
        label="Tender map"
        title="Where the work is"
        action={
          <ButtonLink to="/map" size="sm">
            Full map & rankings <ArrowRight className="size-3.5" aria-hidden="true" />
          </ButtonLink>
        }
      >
        Open tenders by state. Hover or tap a state to see what is open there.
      </SectionHeading>
      <div className="panel grid lg:grid-cols-[1.45fr_1fr]">
        <div className="border-b border-line p-4 sm:p-8 lg:border-r lg:border-b-0">
          <div className="mx-auto w-full max-w-xl">
            {map.isLoading ? <Skeleton className="aspect-[600/674] w-full rounded-lg" /> : <IndiaMap data={map.data} selected={current} onSelect={setSelected} />}
          </div>
        </div>
        <div className="p-5 sm:p-8">
          {current ? <StatePanel state={current} stat={stat} /> : <Skeleton className="h-64 w-full" />}
          <TopStates data={map.data} selected={current} onSelect={setSelected} />
        </div>
      </div>
    </Section>
  );
}

// --- 02 Sectors ------------------------------------------------------------------------

const SECTOR_COLS = "grid-cols-[minmax(0,1fr)_40px_86px] gap-3 sm:grid-cols-[minmax(0,1fr)_56px_56px_84px] sm:gap-4";

function SectorTable({ rows, max }: { rows: SectorStat[]; max: number }) {
  return (
    <div>
      <div className={cx("label grid items-center border-b border-line px-4 py-2.5 sm:px-5", SECTOR_COLS)} aria-hidden="true">
        <span>Sector</span>
        <span className="text-right">Open</span>
        <span className="hidden text-right sm:block">≤ 7d</span>
        <span className="text-right">Value</span>
      </div>
      <ul>
        {rows.map((s) => (
          <li key={s.slug} className="border-b border-line last:border-b-0">
            <Link
              to={`/tenders?sector=${s.slug}`}
              className={cx("group relative grid items-center px-4 py-3 transition-colors hover:bg-surface-2/70 sm:px-5", SECTOR_COLS)}
            >
              <span className="absolute inset-y-0 left-0 w-0.5 bg-signal opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
              <span className="min-w-0">
                <span className="flex items-center gap-2.5 text-sm text-ink">
                  <SectorIcon slug={s.slug} className="size-4 shrink-0 text-ink-3 transition-colors group-hover:text-signal-text" />
                  <span className="truncate">{sectorMeta(s.slug).label}</span>
                </span>
                <span className="bar mt-2 ml-[26px] block max-w-48" aria-hidden="true">
                  <span style={{ width: `${max ? Math.max(2, (s.open / max) * 100) : 0}%` }} />
                </span>
              </span>
              <span className="num text-right text-sm text-ink">{formatCount(s.open)}</span>
              <span className="num hidden text-right text-sm text-ink-2 sm:block">{formatCount(s.closing_this_week)}</span>
              <span className={cx("num text-right text-sm whitespace-nowrap", s.value_inr ? "text-ink-2" : "text-ink-3")}>{s.value_inr ? formatInr(s.value_inr, { short: true }) : "—"}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SectorsSection() {
  const sectors = useQuery({ queryKey: ["sectors"], queryFn: api.sectors });
  const rows = [...(sectors.data ?? [])].sort((a, b) => b.open - a.open);
  const max = rows[0]?.open ?? 0;
  const half = Math.ceil(rows.length / 2);
  return (
    <Section>
      <SectionHeading
        index="02"
        label="Sectors"
        title="Every tender, sorted by the kind of work"
        action={
          <ButtonLink to="/sectors" size="sm">
            All sectors <ArrowRight className="size-3.5" aria-hidden="true" />
          </ButtonLink>
        }
      >
        Classified from each tender's title and the portal's own category, from road building to CCTV and lab equipment.
      </SectionHeading>
      <div className="panel overflow-hidden">
        {sectors.isLoading ? (
          <div className="grid lg:grid-cols-2">
            {Array.from({ length: 2 }, (_, c) => (
              <div key={c} className="divide-y divide-line lg:[&:first-child]:border-r lg:[&:first-child]:border-line">
                {Array.from({ length: 6 }, (_, i) => (
                  <div key={i} className="flex justify-between px-5 py-4">
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-4 w-24" />
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : (
          <div className="grid lg:grid-cols-2">
            <div className="border-b border-line lg:border-r lg:border-b-0">
              <SectorTable rows={rows.slice(0, half)} max={max} />
            </div>
            <SectorTable rows={rows.slice(half)} max={max} />
          </div>
        )}
      </div>
      <p className="mt-3 text-xs text-ink-3">Bars compare open tenders across sectors. Value is the sum of tenders that disclose one.</p>
    </Section>
  );
}

// --- 03 Closing soon -------------------------------------------------------------------

function ClosingSoon() {
  const q = useQuery({ queryKey: ["closing-soon"], queryFn: () => api.tenders({ ...DEFAULT_FILTERS, sort: "closing" }) });
  return (
    <Section>
      <SectionHeading
        index="03"
        label="Deadlines"
        title="Closing soon"
        action={
          <ButtonLink to="/tenders?sort=closing" size="sm">
            See all <ArrowRight className="size-3.5" aria-hidden="true" />
          </ButtonLink>
        }
      >
        Bid submission closes on these first. Red means three days or less.
      </SectionHeading>
      <div className="panel overflow-hidden">
        <TenderListHeader />
        {q.isLoading
          ? Array.from({ length: 4 }, (_, i) => <TenderRowSkeleton key={i} />)
          : q.data?.results.slice(0, 6).map((t) => <TenderRow key={t.id} t={t} />)}
      </div>
    </Section>
  );
}

// --- Alerts ----------------------------------------------------------------------------

const EXAMPLE: AlertCriteria = { states: ["Chhattisgarh"], pin_prefixes: [], sectors: ["roads", "buildings"], keywords: "", min_value_inr: "1000000" };

/** An example alert, written out like a config readout, with its live match count. */
function AlertSpec() {
  const preview = useQuery({ queryKey: ["alert-preview", EXAMPLE], queryFn: () => api.previewAlert(EXAMPLE), retry: false });
  const rows: [string, ReactNode][] = [
    ["Where", "Chhattisgarh, every PIN area"],
    ["What", "Roads & Bridges, Buildings & Civil"],
    ["Min value", "₹10 lakh"],
    ["Send", "after every hourly crawl, only if new"],
  ];
  return (
    <div className="panel ticks bg-surface/80 backdrop-blur-sm">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <p className="num text-xs text-ink-2">alerts / roads-chhattisgarh</p>
        <span className="label flex items-center gap-2 text-good">
          <span className="live-dot" aria-hidden="true" /> Active
        </span>
      </div>
      <dl className="divide-y divide-line">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[92px_1fr] gap-4 px-4 py-3">
            <dt className="label pt-0.5">{k}</dt>
            <dd className="num text-[13px] text-ink">{v}</dd>
          </div>
        ))}
      </dl>
      {preview.data && (
        <div className="flex items-baseline justify-between gap-4 border-t border-line bg-surface-2/60 px-4 py-3">
          <span className="label">Matching now</span>
          <span className="num text-ink">
            <span className="text-xl font-medium text-signal-text">{formatCount(preview.data.count)}</span> <span className="text-xs text-ink-3">open tenders</span>
          </span>
        </div>
      )}
    </div>
  );
}

function AlertsCta() {
  // Always a dark stage, on both themes: the .dark class swaps the tokens inside it.
  return (
    <section>
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <div className="dark relative overflow-hidden rounded-lg border border-line bg-bg text-ink">
          <InterfaceLines density={0.9} className="[mask-image:linear-gradient(to_right,transparent,black_45%)]" />
          <div
            className="pointer-events-none absolute inset-0 bg-[radial-gradient(55%_80%_at_88%_0%,color-mix(in_srgb,var(--signal)_13%,transparent),transparent_70%)]"
            aria-hidden="true"
          />
          <div className="relative grid gap-10 p-6 sm:p-10 lg:grid-cols-[1.1fr_1fr] lg:items-center lg:gap-16 lg:p-14">
            <div>
              <p className="eyebrow">Email alerts</p>
              <h2 className="mt-5 text-3xl font-semibold sm:text-[40px] sm:leading-[1.08]">Hear about tenders in your area first.</h2>
              <p className="mt-4 max-w-lg text-ink-2">
                Choose states, PIN areas and the kind of work you do. After each hourly crawl we email only what is new, so nothing closes before you see it.
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-3">
                <ButtonLink variant="primary" size="lg" to="/alerts">
                  Create a free alert <ArrowRight className="size-4" aria-hidden="true" />
                </ButtonLink>
                <span className="text-sm text-ink-3">Free. One click to unsubscribe.</span>
              </div>
            </div>
            <AlertSpec />
          </div>
        </div>
      </div>
    </section>
  );
}

// --- 04 Coverage -----------------------------------------------------------------------

function Coverage() {
  return (
    <Section className="[&>div]:pb-0">
      <SectionHeading index="04" label="Coverage" title="What is in the index" />
      <div className="grid gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-2">
        <div className="bg-surface p-6 sm:p-8">
          <Tag tone="good">
            <span className="live-dot" aria-hidden="true" /> Live
          </Tag>
          <h3 className="mt-5 text-xl font-semibold text-ink">Government tenders</h3>
          <p className="mt-2 max-w-md text-ink-2">Central ministries, PSUs, AIIMS, IITs, defence and state portals, refreshed every hour.</p>
          <Link to="/tenders" className={cx(textLink, "mt-6")}>
            Explore government tenders <ArrowRight className="size-3.5" aria-hidden="true" />
          </Link>
        </div>
        <div className="bg-surface p-6 sm:p-8">
          <Tag tone="signal">Coming soon</Tag>
          <h3 className="mt-5 text-xl font-semibold text-ink">Private tenders</h3>
          <p className="mt-2 max-w-md text-ink-2">RFQs and RFPs from private companies, in the same search and the same alerts.</p>
          <Link to="/private" className={cx(textLink, "mt-6")}>
            Join the waitlist <ArrowRight className="size-3.5" aria-hidden="true" />
          </Link>
        </div>
      </div>
      <p className="num mt-4 text-xs text-ink-3">Crawled hourly from public pages · one request per second · always confirm on the official portal</p>
    </Section>
  );
}

export default function Home() {
  return (
    <>
      <Hero />
      <Readout />
      <MapSection />
      <SectorsSection />
      <ClosingSoon />
      <AlertsCta />
      <Coverage />
    </>
  );
}
