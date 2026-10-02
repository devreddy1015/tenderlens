import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Bell, Briefcase, Clock, MapPin, Search, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { IndiaMap } from "../components/IndiaMap";
import { TenderCard, TenderCardSkeleton } from "../components/TenderCard";
import { Button, Card, cx, SectionHeading, Skeleton } from "../components/ui";
import { api, DEFAULT_FILTERS, type StateStat } from "../lib/api";
import { formatCount, formatInr, timeAgo } from "../lib/format";
import { SECTORS, SectorIcon, sectorMeta } from "../lib/sectors";

const QUICK = ["roads", "it", "security", "health", "electrical", "buildings"];

function Hero() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  const sectors = useQuery({ queryKey: ["sectors"], queryFn: api.sectors });
  const totalValue = sectors.data?.reduce((s, x) => s + Number(x.value_inr ?? 0), 0);
  const states = stats.data?.by_state.filter((s) => s.state !== "Unknown").length;

  return (
    <section className="hero-glow relative overflow-hidden border-b border-line">
      <div className="mx-auto grid max-w-7xl items-start gap-10 px-4 pt-14 pb-12 sm:px-6 sm:pt-20 sm:pb-16 lg:grid-cols-[1.45fr_1fr]">
        <div>
        <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-line bg-surface/70 px-3 py-1 text-xs font-medium text-ink-2 backdrop-blur">
          <span className="size-1.5 rounded-full bg-good" aria-hidden="true" />
          Live data · updated {timeAgo(stats.data?.last_crawl?.finished)}
        </p>
        <h1 className="max-w-3xl text-4xl font-extrabold tracking-tight text-ink sm:text-6xl sm:leading-[1.05] lg:text-[3.25rem]">
          Find government tenders <span className="text-brand">before they close.</span>
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-ink-2">
          Every open tender from India's central e-procurement portal, in one place. Search it, see it on a map, and get an email when something opens in your area.
        </p>

        <form
          className="mt-8 flex max-w-2xl flex-col gap-2 rounded-2xl border border-line bg-surface p-2 shadow-xl shadow-black/5 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            nav(`/tenders${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`);
          }}
          role="search"
        >
          <label className="flex flex-1 items-center gap-3 px-3">
            <Search className="size-5 shrink-0 text-ink-3" aria-hidden="true" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Road repair, CCTV, solar plant, AIIMS…"
              className="h-12 w-full bg-transparent text-base text-ink placeholder:text-ink-3 focus:outline-none"
              aria-label="Search tenders"
            />
          </label>
          <Button type="submit" variant="primary" size="lg" className="rounded-xl">
            Search tenders
          </Button>
        </form>

        <div className="mt-4 flex flex-wrap gap-2">
          {QUICK.map((slug) => (
            <Link
              key={slug}
              to={`/tenders?sector=${slug}`}
              className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-ink-2 transition-colors hover:border-brand hover:text-brand"
            >
              <SectorIcon slug={slug} className="size-4" />
              {sectorMeta(slug).label}
            </Link>
          ))}
        </div>

        <dl className="mt-12 grid max-w-4xl grid-cols-2 gap-px overflow-hidden rounded-2xl border border-line bg-line sm:grid-cols-4">
          {[
            { label: "Open tenders", value: stats.data && formatCount(stats.data.open_tenders) },
            { label: "Closing in 7 days", value: stats.data && formatCount(stats.data.closing_this_week) },
            { label: "Disclosed value", value: totalValue !== undefined && formatInr(totalValue, { short: true }) },
            { label: "States & UTs", value: states !== undefined && formatCount(states) },
          ].map((s) => (
            <div key={s.label} className="bg-surface px-5 py-4">
              <dt className="text-sm text-ink-2">{s.label}</dt>
              <dd className="mt-1 text-2xl font-bold tracking-tight text-ink">{s.value || <Skeleton className="h-8 w-20" />}</dd>
            </div>
          ))}
        </dl>
        </div>
        <JustPublished />
      </div>
    </section>
  );
}

function JustPublished() {
  const q = useQuery({ queryKey: ["newest"], queryFn: () => api.tenders({ ...DEFAULT_FILTERS, sort: "newest" }) });
  return (
    <div className="hidden rounded-3xl border border-line bg-surface/80 p-5 shadow-2xl shadow-black/5 backdrop-blur lg:block">
      <div className="mb-4 flex items-center justify-between">
        <p className="flex items-center gap-2 text-sm font-semibold text-ink">
          <span className="relative flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-good opacity-60" />
            <span className="relative inline-flex size-2 rounded-full bg-good" />
          </span>
          Just published
        </p>
        <Link to="/tenders?sort=newest" className="text-xs font-semibold text-brand hover:underline">
          See newest
        </Link>
      </div>
      <ul className="divide-y divide-line">
        {q.isLoading
          ? Array.from({ length: 4 }, (_, i) => (
              <li key={i} className="py-3">
                <Skeleton className="mb-2 h-4 w-full" />
                <Skeleton className="h-3 w-1/2" />
              </li>
            ))
          : q.data?.results.slice(0, 4).map((t) => (
              <li key={t.id} className="py-3 first:pt-0 last:pb-0">
                <Link to={`/tenders/${t.id}`} className="group flex gap-3">
                  <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand">
                    <SectorIcon slug={t.sector} className="size-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="line-clamp-2 text-sm font-medium text-ink group-hover:text-brand">{t.title}</span>
                    <span className="mt-0.5 block truncate text-xs text-ink-3">
                      {t.state || "India"} · {formatInr(t.value_inr, { short: true })} · published {timeAgo(t.published_at)}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
      </ul>
    </div>
  );
}

export function StatePanel({ stat, state }: { stat?: StateStat; state: string }) {
  return (
    <div>
      <p className="text-xs font-semibold tracking-wider text-ink-3 uppercase">Selected state</p>
      <h3 className="mt-1 flex items-center gap-2 text-2xl font-bold tracking-tight text-ink">
        <MapPin className="size-5 text-brand" aria-hidden="true" />
        {state}
      </h3>
      <dl className="mt-5 grid grid-cols-2 gap-4">
        <div>
          <dt className="text-sm text-ink-2">Open tenders</dt>
          <dd className="text-3xl font-bold text-ink">{formatCount(stat?.open)}</dd>
        </div>
        <div>
          <dt className="text-sm text-ink-2">Closing in 7 days</dt>
          <dd className="text-3xl font-bold text-ink">{formatCount(stat?.closing_this_week)}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-sm text-ink-2">Disclosed value</dt>
          <dd className="text-lg font-semibold text-ink">{formatInr(stat?.value_inr)}</dd>
        </div>
        {stat?.top_sector && (
          <div className="col-span-2">
            <dt className="text-sm text-ink-2">Most common work</dt>
            <dd className="mt-1 inline-flex items-center gap-1.5 font-medium text-ink">
              <SectorIcon slug={stat.top_sector} />
              {sectorMeta(stat.top_sector).label}
            </dd>
          </div>
        )}
      </dl>
      <div className="mt-6 flex flex-wrap gap-2">
        <Link to={`/tenders?state=${encodeURIComponent(state)}`} className="inline-flex h-10 items-center gap-2 rounded-full bg-brand px-4 text-sm font-semibold text-brand-ink hover:brightness-110">
          View tenders <ArrowRight className="size-4" />
        </Link>
        <Link to={`/alerts?state=${encodeURIComponent(state)}`} className="inline-flex h-10 items-center gap-2 rounded-full border border-line px-4 text-sm font-semibold text-ink hover:bg-surface-2">
          <Bell className="size-4" /> Alert me
        </Link>
      </div>
    </div>
  );
}

function TopStates({ data, selected, onSelect }: { data?: StateStat[]; selected?: string; onSelect: (s: string) => void }) {
  const top = (data ?? []).slice(0, 6);
  const max = top[0]?.open ?? 1;
  if (!top.length) return null;
  return (
    <div className="mt-8 border-t border-line pt-6">
      <p className="mb-3 text-xs font-semibold tracking-wider text-ink-3 uppercase">Most open tenders</p>
      <ul className="space-y-1">
        {top.map((s) => (
          <li key={s.state}>
            <button
              onClick={() => onSelect(s.state)}
              aria-pressed={s.state === selected}
              className={cx("w-full rounded-lg px-2 py-1.5 text-left text-sm transition-colors hover:bg-surface-2", s.state === selected && "bg-surface-2")}
            >
              <span className="flex justify-between gap-2">
                <span className={s.state === selected ? "font-semibold text-ink" : "text-ink-2"}>{s.state}</span>
                <span className="tabular-nums text-ink">{formatCount(s.open)}</span>
              </span>
              <span className="mt-1 block h-1 rounded-full bg-surface-2">
                <span className="block h-1 rounded-full bg-brand" style={{ width: `${(s.open / max) * 100}%` }} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function MapSection() {
  const map = useQuery({ queryKey: ["map", ""], queryFn: () => api.map() });
  const [selected, setSelected] = useState<string>();
  const current = selected ?? map.data?.[0]?.state;
  const stat = map.data?.find((s) => s.state === current);
  return (
    <section className="mx-auto max-w-7xl px-4 pt-16 sm:px-6">
      <SectionHeading
        eyebrow="Tender map"
        title="Where the work is"
        action={
          <Link to="/map" className="inline-flex items-center gap-1 text-sm font-semibold text-brand hover:underline">
            Full map & rankings <ArrowRight className="size-4" />
          </Link>
        }
      >
        Open tenders by state. Hover or tap a state to see what is open there.
      </SectionHeading>
      <Card className="grid gap-8 p-4 sm:p-6 lg:grid-cols-[1.5fr_1fr]">
        <div className="mx-auto w-full max-w-xl">
          {map.isLoading ? <Skeleton className="aspect-[600/674] w-full rounded-2xl" /> : <IndiaMap data={map.data} selected={current} onSelect={setSelected} />}
        </div>
        <div className="lg:border-l lg:border-line lg:pl-8">
          {current ? <StatePanel state={current} stat={stat} /> : <Skeleton className="h-64 w-full" />}
          <TopStates data={map.data} selected={current} onSelect={setSelected} />
        </div>
      </Card>
    </section>
  );
}

function SectorsSection() {
  const sectors = useQuery({ queryKey: ["sectors"], queryFn: api.sectors });
  return (
    <section className="mx-auto max-w-7xl px-4 pt-20 sm:px-6">
      <SectionHeading eyebrow="Browse by type" title="Tenders by sector">
        Every tender is sorted by the kind of work, from road building to CCTV and lab equipment.
      </SectionHeading>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {(sectors.data ?? SECTORS.map((s) => ({ ...s, open: undefined, value_inr: null, description: "", closing_this_week: 0 })))
          .filter((s) => s.slug !== "other")
          .map((s) => (
            <Link
              key={s.slug}
              to={`/tenders?sector=${s.slug}`}
              className="group rounded-2xl border border-line bg-surface p-4 transition-all hover:-translate-y-0.5 hover:border-brand hover:shadow-lg hover:shadow-black/5 sm:p-5"
            >
              <span className="grid size-10 place-items-center rounded-xl bg-brand-soft text-brand">
                <SectorIcon slug={s.slug} className="size-5" />
              </span>
              <p className="mt-4 font-semibold text-ink group-hover:text-brand">{sectorMeta(s.slug).label}</p>
              <p className="mt-1 text-sm text-ink-2">
                {s.open === undefined ? <Skeleton className="h-4 w-24" /> : <>{formatCount(s.open)} open · {formatInr(s.value_inr, { short: true })}</>}
              </p>
            </Link>
          ))}
      </div>
    </section>
  );
}

function ClosingSoon() {
  const q = useQuery({ queryKey: ["closing-soon"], queryFn: () => api.tenders({ ...DEFAULT_FILTERS, sort: "closing" }) });
  return (
    <section className="mx-auto max-w-7xl px-4 pt-20 sm:px-6">
      <SectionHeading
        eyebrow="Don't miss these"
        title="Closing soon"
        action={
          <Link to="/tenders?sort=closing" className="inline-flex items-center gap-1 text-sm font-semibold text-brand hover:underline">
            See all <ArrowRight className="size-4" />
          </Link>
        }
      />
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {q.isLoading
          ? Array.from({ length: 6 }, (_, i) => <TenderCardSkeleton key={i} />)
          : q.data?.results.slice(0, 6).map((t) => <TenderCard key={t.id} t={t} compact />)}
      </div>
    </section>
  );
}

function AlertsCta() {
  return (
    <section className="mx-auto max-w-7xl px-4 pt-20 sm:px-6">
      <div className="relative overflow-hidden rounded-3xl bg-brand px-6 py-10 text-brand-ink sm:px-12 sm:py-14">
        <div className="relative z-10 grid items-center gap-8 lg:grid-cols-[1.4fr_1fr]">
          <div>
            <p className="inline-flex items-center gap-2 text-sm font-semibold opacity-90">
              <Bell className="size-4" /> Email alerts
            </p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">Hear about tenders in your area first.</h2>
            <p className="mt-3 max-w-xl opacity-90">
              Pick a state, a PIN area like Bhilai (490xxx), and the kind of work you do. We email you after every hourly crawl when something new opens. One click to unsubscribe.
            </p>
          </div>
          <div className="flex flex-wrap gap-3 lg:justify-end">
            <Link to="/alerts" className="inline-flex h-12 items-center gap-2 rounded-full bg-white px-6 font-semibold text-[#0d366b] hover:bg-white/90">
              Create a free alert <ArrowRight className="size-4" />
            </Link>
          </div>
        </div>
        <div className="absolute -top-24 -right-24 size-80 rounded-full bg-white/10" aria-hidden="true" />
        <div className="absolute -bottom-32 left-1/3 size-72 rounded-full bg-white/5" aria-hidden="true" />
      </div>
    </section>
  );
}

function PrivateTeaser() {
  return (
    <section className="mx-auto max-w-7xl px-4 pt-20 sm:px-6">
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-6 sm:p-8">
          <span className="grid size-10 place-items-center rounded-xl bg-brand-soft text-brand">
            <Briefcase className="size-5" />
          </span>
          <h3 className="mt-4 text-xl font-bold text-ink">Government tenders</h3>
          <p className="mt-2 text-ink-2">Live now: central ministries, PSUs, AIIMS, IITs, defence and state portals, refreshed every hour.</p>
          <Link to="/tenders" className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-brand hover:underline">
            Explore government tenders <ArrowRight className="size-4" />
          </Link>
        </Card>
        <Card className="relative overflow-hidden p-6 sm:p-8">
          <span className="absolute top-5 right-5 rounded-full bg-brand-soft px-2.5 py-1 text-xs font-semibold text-brand">Coming soon</span>
          <span className="grid size-10 place-items-center rounded-xl bg-surface-2 text-ink-2">
            <Sparkles className="size-5" />
          </span>
          <h3 className="mt-4 text-xl font-bold text-ink">Private tenders</h3>
          <p className="mt-2 text-ink-2">RFQs and RFPs from private companies, in the same search and alerts. Join the waitlist to hear when it launches.</p>
          <Link to="/private" className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-brand hover:underline">
            Join the waitlist <ArrowRight className="size-4" />
          </Link>
        </Card>
      </div>
      <p className="mt-6 flex items-center gap-2 text-xs text-ink-3">
        <Clock className="size-3.5" aria-hidden="true" /> Crawled every hour from public pages, at one request per second.
      </p>
    </section>
  );
}

export default function Home() {
  return (
    <>
      <Hero />
      <MapSection />
      <SectorsSection />
      <ClosingSoon />
      <AlertsCta />
      <PrivateTeaser />
    </>
  );
}
