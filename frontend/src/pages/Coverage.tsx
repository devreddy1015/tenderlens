import { ArrowUpRight, Ban, Braces, DatabaseZap, Scale } from "lucide-react";
import { useState } from "react";
import { Card, cx, EmptyState, PageHeader, Segmented, Skeleton, Stat, Tag } from "../components/ui";
import { errorMessage, type Source } from "../lib/api";
import { formatCount, formatDate, timeAgo } from "../lib/format";
import { useSources } from "../lib/queries";
import { KIND_LABEL, latestRun, runTone } from "../lib/sources";

type Kind = Source["kind"];

function LastRun({ s }: { s: Source }) {
  const r = s.last_run;
  if (!r) return <span className="text-ink-3">Not crawled yet</span>;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Tag tone={runTone(r.status)} className="h-5 px-1.5 text-[11px]">
          {r.status || "unknown"}
        </Tag>
        <span className="num text-xs text-ink-2" title={formatDate(r.finished)}>
          {r.finished ? timeAgo(r.finished) : "in progress"}
        </span>
      </div>
      <p className="num mt-1 text-[11px] text-ink-3">
        +{formatCount(r.new)} new · {formatCount(r.updated)} updated
      </p>
    </div>
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
  { name: "GeM bid data", why: "We read only the public listing pages GeM's robots.txt allows. Data behind its server-side protections is left alone." },
  { name: "CPPP “latest active tenders”", why: "That list sits behind a CAPTCHA. We use the portals' public organisation-wise listings instead." },
];

export default function Coverage() {
  const q = useSources();
  const [kind, setKind] = useState<"all" | Kind>("all");
  const sources = q.data ?? [];
  const kinds = (Object.keys(KIND_LABEL) as Kind[]).filter((k) => sources.some((s) => s.kind === k));
  const rows = [...sources].filter((s) => kind === "all" || s.kind === kind).sort((a, b) => Number(b.enabled) - Number(a.enabled) || b.open_tenders - a.open_tenders);
  const open = sources.reduce((n, s) => n + (s.open_tenders ?? 0), 0);
  const latest = latestRun(sources);

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageHeader kicker="Coverage" title="Where the tenders come from">
        Every tender in TenderLens comes from an official public procurement portal, and every record names and links to it.
      </PageHeader>

      <dl className="mt-8 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-3">
        <Stat className="bg-surface px-5 py-4" label="Portals indexed" value={q.data ? formatCount(sources.filter((s) => s.enabled).length) : <Skeleton className="h-7 w-12" />} />
        <Stat className="bg-surface px-5 py-4" label="Open tenders" value={q.data ? formatCount(open) : <Skeleton className="h-7 w-20" />} />
        <Stat className="col-span-2 bg-surface px-5 py-4 sm:col-span-1" label="Last crawl finished" value={q.data ? timeAgo(latest) : <Skeleton className="h-7 w-24" />} />
      </dl>

      <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
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
        <Card className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <caption className="sr-only">Procurement portals indexed by TenderLens, with their last crawl</caption>
            <thead>
              <tr className="border-b border-line text-left">
                <th className="label px-5 py-3 font-medium">Portal</th>
                <th className="label px-5 py-3 font-medium">Software</th>
                <th className="label px-5 py-3 text-right font-medium">Open tenders</th>
                <th className="label px-5 py-3 font-medium">Last run</th>
                <th className="label px-5 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {q.isLoading
                ? Array.from({ length: 5 }, (_, i) => (
                    <tr key={i} className="border-b border-line last:border-0">
                      <td className="px-5 py-4" colSpan={5}>
                        <Skeleton className="h-4 w-full" />
                      </td>
                    </tr>
                  ))
                : rows.map((s) => (
                    <tr key={s.key} className={cx("border-b border-line align-top last:border-0", !s.enabled && "opacity-70")}>
                      <td className="px-5 py-3.5">
                        <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-ink decoration-line-strong underline-offset-4 hover:underline">
                          {s.name} <ArrowUpRight className="size-3.5 text-ink-3" aria-hidden="true" />
                        </a>
                        <p className="mt-0.5 text-xs text-ink-3">{s.state ?? "All India"}</p>
                      </td>
                      <td className="px-5 py-3.5">
                        <Tag>{KIND_LABEL[s.kind] ?? s.kind}</Tag>
                      </td>
                      <td className="num px-5 py-3.5 text-right text-ink">{formatCount(s.open_tenders)}</td>
                      <td className="px-5 py-3.5">
                        <LastRun s={s} />
                      </td>
                      <td className="px-5 py-3.5">
                        {s.enabled ? (
                          <span className="inline-flex items-center gap-2 text-xs text-ink-2">
                            <span className="live-dot" aria-hidden="true" /> Crawled on schedule
                          </span>
                        ) : (
                          <span className="text-xs text-ink-3">Paused</span>
                        )}
                      </td>
                    </tr>
                  ))}
              {q.data && rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-5 py-6 text-center text-sm text-ink-3">
                    No portals of this kind yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Card>
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
