import { ArrowUpRight, Ban, Braces, DatabaseZap, Scale } from "lucide-react";
import { useState } from "react";
import { Card, cx, EmptyState, PageHeader, Segmented, Skeleton, Stat, Tag } from "../components/ui";
import { errorMessage, type Source } from "../lib/api";
import { formatCount, formatDate, timeAgo } from "../lib/format";
import { useSources } from "../lib/queries";
import { freshness, groupSources, KIND_LABEL, latestSuccess, runTone, STALE_HOURS } from "../lib/sources";

type Kind = Source["kind"];

const FRESH_LABEL = { fresh: "Fresh", stale: "Stale", never: "Not crawled yet" } as const;

/** The freshness we promise: when the last successful crawl finished, plus the newest run
 *  when it differs (running now, or failed since). */
function Freshness({ s }: { s: Source }) {
  const f = freshness(s);
  const r = s.last_run;
  const lastFailed = r && runTone(r.status) === "critical";
  const running = r && !r.finished;
  return (
    <div className="min-w-0">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Tag tone={f === "fresh" ? "good" : f === "stale" ? "critical" : undefined} className="h-5 px-1.5 text-[11px]">
          {FRESH_LABEL[f]}
        </Tag>
        {s.last_success && (
          <span className="num text-xs text-ink-2" title={formatDate(s.last_success)}>
            {timeAgo(s.last_success)}
          </span>
        )}
      </p>
      {running ? (
        <p className="num mt-1 text-[11px] text-signal-text">Crawling now</p>
      ) : lastFailed ? (
        <p className="num mt-1 text-[11px] text-critical">Last attempt {r.status} {r.finished ? timeAgo(r.finished) : ""}</p>
      ) : r ? (
        <p className="num mt-1 text-[11px] text-ink-3">
          +{formatCount(r.new)} new · {formatCount(r.updated)} updated
        </p>
      ) : null}
    </div>
  );
}

const COLS = "md:grid-cols-[minmax(0,1fr)_96px_110px_190px]";

function PortalRows({ title, hint, rows, loading }: { title: string; hint: string; rows: Source[]; loading: boolean }) {
  const id = `portals-${title.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <section className="mt-8" aria-labelledby={id}>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={id} className="font-medium text-ink">
          {title} <span className="num ml-1 text-sm font-normal text-ink-3">{loading ? "" : rows.length}</span>
        </h3>
        <p className="text-xs text-ink-3">{hint}</p>
      </div>
      <Card className="overflow-hidden">
        <div className={cx("label hidden gap-x-5 border-b border-line px-5 py-2.5 md:grid", COLS)} aria-hidden="true">
          <span>Portal</span>
          <span className="text-right">Open tenders</span>
          <span>Schedule</span>
          <span>Last successful crawl</span>
        </div>
        <ul className="divide-y divide-line">
          {loading
            ? Array.from({ length: 4 }, (_, i) => (
                <li key={i} className="px-5 py-4">
                  <Skeleton className="h-4 w-full" />
                </li>
              ))
            : rows.map((s) => (
                <li key={s.key} className={cx("grid grid-cols-[minmax(0,1fr)_auto] gap-x-5 gap-y-2 px-4 py-3.5 sm:px-5", COLS, !s.enabled && "opacity-70")}>
                  <div className="min-w-0">
                    <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 font-medium text-ink decoration-line-strong underline-offset-4 hover:underline">
                      <span className="truncate">{s.name}</span> <ArrowUpRight className="size-3.5 shrink-0 text-ink-3" aria-hidden="true" />
                    </a>
                    <p className="mt-0.5 text-xs text-ink-3">
                      {s.state ?? "All India"} · {KIND_LABEL[s.kind] ?? s.kind}
                    </p>
                  </div>
                  <p className="num text-right text-ink">
                    {formatCount(s.open_tenders)}
                    <span className="block text-[11px] text-ink-3 md:hidden">open</span>
                  </p>
                  <p className="col-span-2 text-xs md:col-span-1 md:pt-0.5">
                    {s.enabled ? (
                      <span className="inline-flex items-center gap-2 text-ink-2">
                        <span className="live-dot" aria-hidden="true" /> Hourly + nightly
                      </span>
                    ) : (
                      <span className="text-ink-3">Paused</span>
                    )}
                  </p>
                  <div className="col-span-2 md:col-span-1">
                    <Freshness s={s} />
                  </div>
                </li>
              ))}
          {!loading && rows.length === 0 && <li className="px-5 py-6 text-center text-sm text-ink-3">No portals of this kind yet.</li>}
        </ul>
      </Card>
    </section>
  );
}

const RULES = [
  {
    icon: Scale,
    title: "Metadata with attribution, never the documents",
    body: "Portal content has no open licence: reusing it needs the publishing department's permission, and it must be accurate and attributed. So we keep each tender's structured details, name the portal that published it, and link out. Documents stay on the portal; we don't republish or frame them.",
  },
  {
    icon: DatabaseZap,
    title: "Polite, public, CAPTCHA-free",
    body: "We read public listing pages only, at most one request per second per portal, with an honest user agent. We never touch or bypass a CAPTCHA, which is why you download tender documents yourself and upload them to the Copilot.",
  },
  {
    icon: Braces,
    title: "Open Contracting format",
    body: "The index is published as OCDS 1.1 release packages, with an ocid per tender and the source portal on every record, so it works with international open-contracting tools.",
  },
];

const NOT_CRAWLED = [
  { name: "IREPS (Indian Railways)", why: "Its robots.txt disallows all crawling, so railway tenders aren't here. Search them on IREPS directly." },
  { name: "GeM bids", why: "GeM's bid data sits behind server-side protections we don't work around. The route to it is GeM's own data-sharing programme." },
  { name: "Award results", why: "Every public results page (GePNIC “Results of Tenders”, CPPP “Result of Tenders”) needs a CAPTCHA before it shows a row, so we don't collect who won." },
  { name: "CPPP “latest active tenders”", why: "That list sits behind a CAPTCHA. We use the portals' public organisation-wise listings instead." },
];

export default function Coverage() {
  const q = useSources();
  const [kind, setKind] = useState<"all" | Kind>("all");
  const sources = q.data ?? [];
  const kinds = (Object.keys(KIND_LABEL) as Kind[]).filter((k) => sources.some((s) => s.kind === k));
  const groups = groupSources(sources.filter((s) => kind === "all" || s.kind === kind));
  const open = sources.reduce((n, s) => n + (s.open_tenders ?? 0), 0);
  const latest = latestSuccess(sources);
  const fresh = sources.filter((s) => freshness(s) === "fresh").length;

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageHeader kicker="Coverage" title="Where the tenders come from">
        Every tender in TenderLens comes from an official public procurement portal, and every record names and links to it. This page shows how fresh each one
        is, honestly.
      </PageHeader>

      <dl className="mt-8 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-4">
        <Stat className="bg-surface px-5 py-4" label="Portals indexed" value={q.data ? formatCount(sources.filter((s) => s.enabled).length) : <Skeleton className="h-7 w-12" />} />
        <Stat className="bg-surface px-5 py-4" label="Open tenders" value={q.data ? formatCount(open) : <Skeleton className="h-7 w-20" />} />
        <Stat
          className="bg-surface px-5 py-4"
          label="Fresh portals"
          value={q.data ? `${formatCount(fresh)} / ${formatCount(sources.length)}` : <Skeleton className="h-7 w-16" />}
          hint={`crawled successfully in the last ${STALE_HOURS} h`}
        />
        <Stat className="bg-surface px-5 py-4" label="Last successful crawl" value={q.data ? timeAgo(latest) : <Skeleton className="h-7 w-24" />} />
      </dl>

      <div className="mt-10 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-ink">Portals</h2>
        {kinds.length > 1 && (
          <Segmented<"all" | Kind>
            label="Portal software"
            value={kind}
            onChange={setKind}
            options={[{ value: "all", label: "All" }, ...kinds.map((k) => ({ value: k, label: KIND_LABEL[k] }))]}
          />
        )}
      </div>

      {q.isError ? (
        <div className="mt-4">
          <EmptyState icon={<DatabaseZap className="size-5" />} title="Couldn't load the source list">
            {errorMessage(q.error)}
          </EmptyState>
        </div>
      ) : (
        <>
          <PortalRows title="Central government, PSUs and defence" hint="All-India portals, most open tenders first" rows={groups.central} loading={q.isLoading} />
          <PortalRows title="States and union territories" hint="One portal per state, alphabetical" rows={groups.states} loading={q.isLoading} />
        </>
      )}

      <section className="mt-14 grid gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-3">
        {RULES.map(({ icon: Icon, title, body }) => (
          <div key={title} className="bg-surface p-6">
            <Icon className="size-[18px] text-signal-text" aria-hidden="true" />
            <h3 className="mt-4 font-medium text-ink">{title}</h3>
            <p className="mt-1.5 text-sm text-ink-2">{body}</p>
          </div>
        ))}
      </section>
      <p className="mt-3 text-xs text-ink-3">
        OCDS feed:{" "}
        <a href="/api/ocds/releases" className="num text-ink-2 underline decoration-line-strong underline-offset-4 hover:text-ink">
          /api/ocds/releases
        </a>{" "}
        (public, paginated, takes the same filters as Explore).
      </p>

      <section className="mt-14">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-ink">
          <Ban className="size-4 text-ink-3" aria-hidden="true" /> What we leave alone
        </h2>
        <dl className="mt-4 divide-y divide-line border-y border-line">
          {NOT_CRAWLED.map((n) => (
            <div key={n.name} className="grid gap-1 py-4 sm:grid-cols-[260px_1fr] sm:gap-6">
              <dt className="text-sm font-medium text-ink">{n.name}</dt>
              <dd className="text-sm text-ink-2">{n.why}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-xs text-ink-3">Missing a portal you bid on? Tell us with the Feedback button.</p>
      </section>
    </div>
  );
}
