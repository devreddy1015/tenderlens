import { useQuery } from "@tanstack/react-query";
import { Bell, Building, ExternalLink, FileSearch, MapPin } from "lucide-react";
import { Link, useParams } from "react-router";
import { TenderCopilot } from "../components/copilot/TenderCopilot";
import { CopyId, TenderCard } from "../components/TenderCard";
import { TrackPanel } from "../components/TrackButton";
import { ButtonAnchor, ButtonLink, Card, cx, EmptyState, Skeleton, Tag } from "../components/ui";
import { api, type TenderDetail } from "../lib/api";
import { closesIn, countdown, formatDate, formatInr, windowUsed } from "../lib/format";
import { SectorIcon, sectorMeta } from "../lib/sectors";

function Timeline({ t }: { t: TenderDetail }) {
  const now = Date.now();
  const steps = [
    { label: "Published", at: t.published_at },
    { label: "Bid submission closes", at: t.closes_at },
    { label: "Bids opened", at: t.opens_at },
  ].filter((s): s is { label: string; at: string } => !!s.at);
  const next = steps.findIndex((s) => new Date(s.at).getTime() >= now);
  return (
    <ol>
      {steps.map((s, i) => {
        const done = new Date(s.at).getTime() < now;
        return (
          <li key={s.label} className="relative grid grid-cols-[14px_1fr] gap-3 pb-6 last:pb-0">
            {i < steps.length - 1 && (
              <span className={cx("absolute top-4 bottom-0 left-[6px] w-px", done ? "bg-signal/60" : "bg-line-strong")} aria-hidden="true" />
            )}
            <span
              className={cx(
                "mt-1 size-[13px] rounded-full border-2",
                done ? "border-signal bg-signal" : i === next ? "border-signal bg-surface" : "border-line-strong bg-surface",
              )}
              aria-hidden="true"
            />
            <div>
              <p className={cx("text-sm font-medium", done || i === next ? "text-ink" : "text-ink-2")}>{s.label}</p>
              <p className="num mt-0.5 text-xs text-ink-3">
                {formatDate(s.at)}
                {done ? " · done" : i === next ? ` · in ${countdown(s.at).text}` : ""}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function Fact({ label, value, strong, mono }: { label: string; value: React.ReactNode; strong?: boolean; mono?: boolean }) {
  // An undisclosed amount is an absence, not a headline: keep it quiet.
  const missing = !value || value === "Not disclosed";
  return (
    <div className="bg-surface px-4 py-3.5">
      <dt className="label">{label}</dt>
      <dd
        className={cx(
          "mt-2 break-words",
          missing ? "text-sm text-ink-3" : strong ? "num text-xl font-medium text-ink" : mono ? "num text-sm text-ink" : "text-sm text-ink",
        )}
      >
        {value || "—"}
      </dd>
    </div>
  );
}

function PanelHead({ children }: { children: React.ReactNode }) {
  return <h2 className="label border-b border-line px-5 py-3">{children}</h2>;
}

const CPPP = "https://eprocure.gov.in/eprocure/app";

/** The portal this tender was crawled from. Detail links on GePNIC portals expire with the
 *  session, so we link the portal's home and give the Tender ID to search for. */
function usePortalUrl(source: string | undefined): string {
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources, staleTime: 5 * 60_000 });
  return sources.data?.find((s) => s.key === source)?.url || CPPP;
}

function BidPanel({ t }: { t: TenderDetail }) {
  const portalUrl = usePortalUrl(t.source);
  const left = countdown(t.closes_at);
  const used = windowUsed(t.published_at, t.closes_at);
  return (
    <Card ticks className="p-5">
      <p className="label">Bid submission</p>
      <p className={cx("num mt-3 text-4xl font-medium tracking-tight", left.closed ? "text-ink-3" : left.urgent ? "text-critical" : "text-ink")}>
        {left.text}
        {!left.closed && <span className="ml-2 font-sans text-sm font-normal tracking-normal text-ink-3">left</span>}
      </p>
      {!left.closed && (
        <div className="mt-4">
          <div className={cx("bar h-1", left.urgent && "bar-critical")} aria-hidden="true">
            <span style={{ width: `${Math.max(3, Math.round(used * 100))}%` }} />
          </div>
          <p className="num mt-1.5 text-right text-[11px] text-ink-3">{Math.round(used * 100)}% of the bidding window used</p>
        </div>
      )}
      <dl className="mt-4 space-y-2 border-t border-line pt-4 text-sm">
        <div className="flex justify-between gap-4">
          <dt className="text-ink-3">Published</dt>
          <dd className="num text-ink-2">{formatDate(t.published_at)}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-ink-3">Closes</dt>
          <dd className="num text-ink">{formatDate(t.closes_at)}</dd>
        </div>
        {t.opens_at && (
          <div className="flex justify-between gap-4">
            <dt className="text-ink-3">Bids open</dt>
            <dd className="num text-ink-2">{formatDate(t.opens_at)}</dd>
          </div>
        )}
      </dl>
      <ButtonAnchor variant="primary" href={portalUrl} className="mt-5 h-11 w-full">
        Open official portal <ExternalLink className="size-4" aria-hidden="true" />
      </ButtonAnchor>
      <div className="mt-2">
        <TrackPanel tender={t} />
      </div>
      <p className="mt-3 text-xs leading-relaxed text-ink-3">
        Portal links expire with your session, so search the portal for Tender ID <span className="num text-ink-2">{t.source_tender_id}</span>. Download
        documents and bid there.
      </p>
    </Card>
  );
}

function WatchPanel({ t }: { t: TenderDetail }) {
  return (
    <Card className="p-5">
      <p className="label flex items-center gap-2">
        <Bell className="size-3.5 text-signal-text" aria-hidden="true" /> Watch
      </p>
      <p className="mt-3 font-medium text-ink">Get more like this</p>
      <p className="mt-1 text-sm text-ink-2">
        Email me when a new {sectorMeta(t.sector).label.toLowerCase()} tender opens in {t.state || "India"}.
      </p>
      <ButtonLink to={`/alerts?${new URLSearchParams({ ...(t.state ? { state: t.state } : {}), sector: t.sector })}`} className="mt-4 w-full">
        Create alert
      </ButtonLink>
    </Card>
  );
}

export default function TenderPage() {
  const id = Number(useParams().id);
  const q = useQuery({ queryKey: ["tender", id], queryFn: () => api.tender(id), enabled: Number.isFinite(id) });
  const similar = useQuery({ queryKey: ["similar", id], queryFn: () => api.similar(id), enabled: q.isSuccess });

  if (q.isError) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-20">
        <EmptyState icon={<FileSearch className="size-5" />} title="Tender not found">
          It may have been removed from the portal.{" "}
          <Link to="/tenders" className="font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-signal">
            Search tenders
          </Link>
        </EmptyState>
      </div>
    );
  }
  const t = q.data;
  const portalUrl = usePortalUrl(t?.source);
  const due = t ? closesIn(t.closes_at) : null;
  const chain = t?.org_chain.split("||").map((s) => s.trim()).filter(Boolean) ?? [];

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <nav aria-label="Breadcrumb" className="num mb-8 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-3">
        <Link to="/tenders" className="hover:text-ink">
          Tenders
        </Link>
        <span aria-hidden="true">/</span>
        {t ? (
          <>
            <Link to={`/tenders?sector=${t.sector}`} className="hover:text-ink">
              {sectorMeta(t.sector).label}
            </Link>
            <span aria-hidden="true">/</span>
            <span className="truncate text-ink-2" aria-current="page">
              {t.source_tender_id}
            </span>
          </>
        ) : (
          <Skeleton className="h-3 w-48" />
        )}
      </nav>

      {!t ? (
        <div className="grid gap-10 lg:grid-cols-[1fr_340px]">
          <div className="space-y-4">
            <Skeleton className="h-6 w-56" />
            <Skeleton className="h-9 w-full max-w-3xl" />
            <Skeleton className="h-4 w-80" />
            <Skeleton className="mt-6 h-56 w-full rounded-lg" />
          </div>
          <Skeleton className="h-80 w-full rounded-lg" />
        </div>
      ) : (
        <div className="grid gap-10 lg:grid-cols-[1fr_340px]">
          <div className="min-w-0">
            <div className="mb-4 flex flex-wrap items-center gap-2">
              {due &&
                (due.closed ? (
                  <Tag>Closed</Tag>
                ) : due.urgent ? (
                  <Tag tone="critical">Closing soon</Tag>
                ) : (
                  <Tag tone="good">
                    <span className="live-dot" aria-hidden="true" /> Open
                  </Tag>
                ))}
              <Link to={`/tenders?sector=${t.sector}`} className="tag hover:border-line-strong hover:text-ink">
                <SectorIcon slug={t.sector} className="size-3.5" />
                {sectorMeta(t.sector).label}
              </Link>
              {t.category && <Tag>{t.category}</Tag>}
              {t.tender_type && <Tag>{t.tender_type}</Tag>}
            </div>
            <h1 className={cx("leading-[1.2] font-semibold text-ink [text-wrap:pretty]", t.title.length > 110 ? "text-xl sm:text-[26px]" : "text-2xl sm:text-[32px]")}>
              {t.title}
            </h1>
            <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm text-ink-2">
              <span className="inline-flex min-w-0 items-center gap-1.5">
                <Building className="size-4 shrink-0 text-ink-3" aria-hidden="true" />
                {t.buyer ? (
                  <Link to={`/tenders?buyer=${t.buyer.id}`} className="underline decoration-line-strong underline-offset-4 hover:text-ink hover:decoration-signal">
                    {t.buyer.canonical_name}
                  </Link>
                ) : (
                  t.buyer_raw
                )}
              </span>
              {(t.location || t.state) && (
                <span className="inline-flex items-center gap-1.5">
                  <MapPin className="size-4 shrink-0 text-ink-3" aria-hidden="true" />
                  {[t.location, t.pincode, t.state].filter(Boolean).join(", ")}
                </span>
              )}
            </div>

            <section className="mt-10" aria-labelledby="facts">
              <h2 id="facts" className="label mb-3">
                Key facts
              </h2>
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-3 [&>*:last-child]:col-span-2 sm:[&>*:last-child]:col-span-1">
                <Fact label="Tender value" value={formatInr(t.value_inr)} strong />
                <Fact label="EMD" value={formatInr(t.emd_inr)} strong />
                <Fact label="Tender fee" value={formatInr(t.fee_inr)} mono />
                <Fact label="Tender ID" value={<span className="-ml-1 inline-block max-w-full [&_button]:max-w-full [&_button]:break-all [&_button]:text-left [&_button]:text-sm [&_button]:text-ink"><CopyId id={t.source_tender_id} /></span>} />
                <Fact label="Reference number" value={t.ref_no} mono />
                <Fact label="Tender type" value={t.tender_type} />
                <Fact label="Portal category" value={t.product_category} />
                <Fact label="First seen" value={formatDate(t.first_seen, false)} mono />
                <Fact label="Last checked" value={formatDate(t.last_seen)} mono />
              </dl>
            </section>

            <div className="mt-8 lg:hidden">
              <BidPanel t={t} />
            </div>

            <div className="mt-8">
              <TenderCopilot tender={t} portalUrl={portalUrl} />
            </div>

            <div className="mt-8 grid gap-6 md:grid-cols-2">
              <Card>
                <PanelHead>Timeline</PanelHead>
                <div className="p-5">
                  <Timeline t={t} />
                </div>
              </Card>
              <Card>
                <PanelHead>Organisation</PanelHead>
                <ol className="space-y-2.5 p-5">
                  {chain.map((c, i) => (
                    <li key={i} className="flex items-start text-sm" style={{ paddingLeft: `${Math.max(0, i - 1) * 18}px` }}>
                      {i > 0 && <span className="mt-0.5 mr-2.5 h-2.5 w-3 shrink-0 rounded-bl-[3px] border-b border-l border-line-strong" aria-hidden="true" />}
                      <span className={i === 0 ? "font-medium text-ink" : "text-ink-2"}>{c}</span>
                    </li>
                  ))}
                </ol>
              </Card>
            </div>

            <div className="mt-6 lg:hidden">
              <WatchPanel t={t} />
            </div>
          </div>

          <aside className="hidden space-y-5 lg:sticky lg:top-20 lg:block lg:self-start">
            <BidPanel t={t} />
            <WatchPanel t={t} />
          </aside>
        </div>
      )}

      {(similar.data?.length ?? 0) > 0 && (
        <section className="mt-16 border-t border-line pt-10">
          <div className="mb-6 flex items-end justify-between gap-4">
            <div>
              <p className="label mb-2">Related</p>
              <h2 className="text-xl font-semibold text-ink">Similar open tenders</h2>
            </div>
            {t && (
              <Link to={`/tenders?sector=${t.sector}`} className="text-sm text-ink-2 underline decoration-line-strong underline-offset-4 hover:text-ink hover:decoration-signal">
                All {sectorMeta(t.sector).label.toLowerCase()}
              </Link>
            )}
          </div>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {similar.data!.map((s) => (
              <TenderCard key={s.id} t={s} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
