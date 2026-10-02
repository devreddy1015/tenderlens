import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Bell, Building, ExternalLink, FileSearch, MapPin } from "lucide-react";
import { Link, useParams } from "react-router";
import { AskDocuments } from "../components/AskDocuments";
import { ClosingBadge, CopyId, TenderCard } from "../components/TenderCard";
import { Card, cx, EmptyState, Skeleton } from "../components/ui";
import { api, type TenderDetail } from "../lib/api";
import { closesIn, formatDate, formatInr } from "../lib/format";
import { SectorIcon, sectorMeta } from "../lib/sectors";

function Timeline({ t }: { t: TenderDetail }) {
  const now = Date.now();
  const steps = [
    { label: "Published", at: t.published_at },
    { label: "Bid submission closes", at: t.closes_at },
    { label: "Bids opened", at: t.opens_at },
  ].filter((s): s is { label: string; at: string } => !!s.at);
  return (
    <ol className="relative space-y-5 border-l-2 border-line pl-6">
      {steps.map((s) => {
        const done = new Date(s.at).getTime() < now;
        return (
          <li key={s.label} className="relative">
            <span
              className={cx("absolute top-1 -left-[31px] size-3.5 rounded-full border-2", done ? "border-brand bg-brand" : "border-line bg-surface")}
              aria-hidden="true"
            />
            <p className="text-sm font-medium text-ink">{s.label}</p>
            <p className="text-sm text-ink-2">
              {formatDate(s.at)} {done && <span className="text-ink-3">· done</span>}
            </p>
          </li>
        );
      })}
    </ol>
  );
}

function Fact({ label, value, strong }: { label: string; value: React.ReactNode; strong?: boolean }) {
  return (
    <div>
      <dt className="text-sm text-ink-3">{label}</dt>
      <dd className={cx("mt-0.5", strong ? "text-xl font-bold text-ink" : "text-ink")}>{value || "—"}</dd>
    </div>
  );
}

export default function TenderPage() {
  const id = Number(useParams().id);
  const q = useQuery({ queryKey: ["tender", id], queryFn: () => api.tender(id), enabled: Number.isFinite(id) });
  const similar = useQuery({ queryKey: ["similar", id], queryFn: () => api.similar(id), enabled: q.isSuccess });

  if (q.isError) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16">
        <EmptyState icon={<FileSearch className="size-6" />} title="Tender not found">
          It may have been removed from the portal. <Link to="/tenders" className="text-brand hover:underline">Search tenders</Link>
        </EmptyState>
      </div>
    );
  }
  const t = q.data;
  const due = t ? closesIn(t.closes_at) : null;
  const chain = t?.org_chain.split("||").map((s) => s.trim()).filter(Boolean) ?? [];

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <Link to="/tenders" className="mb-6 inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink">
        <ArrowLeft className="size-4" /> All tenders
      </Link>

      {!t ? (
        <div className="space-y-4">
          <Skeleton className="h-6 w-40 rounded-full" />
          <Skeleton className="h-10 w-full max-w-3xl" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : (
        <div className="grid gap-8 lg:grid-cols-[1fr_340px]">
          <div>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
              <Link to={`/tenders?sector=${t.sector}`} className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-3 py-1 font-medium text-brand hover:underline">
                <SectorIcon slug={t.sector} className="size-4" />
                {sectorMeta(t.sector).label}
              </Link>
              {t.category && <span className="rounded-full bg-surface-2 px-3 py-1 text-ink-2">{t.category}</span>}
              {due && (
                <span className={cx("rounded-full px-3 py-1 font-medium", due.closed ? "bg-surface-2 text-ink-3" : due.urgent ? "bg-critical/10 text-critical" : "bg-surface-2 text-ink-2")}>
                  {due.closed ? "Closed" : "Open"}
                </span>
              )}
            </div>
            <h1 className="text-2xl leading-tight font-bold tracking-tight text-ink sm:text-3xl">{t.title}</h1>
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-2">
              <span className="inline-flex items-center gap-1.5">
                <Building className="size-4 text-ink-3" />
                {t.buyer ? (
                  <Link to={`/tenders?buyer=${t.buyer.id}`} className="hover:text-brand hover:underline">
                    {t.buyer.canonical_name}
                  </Link>
                ) : (
                  t.buyer_raw
                )}
              </span>
              {(t.location || t.state) && (
                <span className="inline-flex items-center gap-1.5">
                  <MapPin className="size-4 text-ink-3" />
                  {[t.location, t.pincode, t.state].filter(Boolean).join(", ")}
                </span>
              )}
            </div>

            <Card className="mt-6 p-5 sm:p-6">
              <dl className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3">
                <Fact label="Tender value" value={formatInr(t.value_inr)} strong />
                <Fact label="EMD" value={formatInr(t.emd_inr)} strong />
                <Fact label="Tender fee" value={formatInr(t.fee_inr)} />
                <Fact label="Tender ID" value={<CopyId id={t.source_tender_id} />} />
                <Fact label="Reference number" value={t.ref_no} />
                <Fact label="Tender type" value={t.tender_type} />
                <Fact label="Portal category" value={t.product_category} />
                <Fact label="First seen by TenderLens" value={formatDate(t.first_seen, false)} />
                <Fact label="Last checked" value={formatDate(t.last_seen)} />
              </dl>
            </Card>

            <div className="mt-6">
              <AskDocuments tenderId={t.source_tender_id} />
            </div>

            <div className="mt-6 grid gap-6 md:grid-cols-2">
              <Card className="p-5 sm:p-6">
                <h2 className="mb-4 font-semibold text-ink">Timeline</h2>
                <Timeline t={t} />
              </Card>
              <Card className="p-5 sm:p-6">
                <h2 className="mb-4 font-semibold text-ink">Organisation</h2>
                <ol className="space-y-2">
                  {chain.map((c, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm" style={{ paddingLeft: `${i * 12}px` }}>
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-ink-3" aria-hidden="true" />
                      <span className={i === 0 ? "font-medium text-ink" : "text-ink-2"}>{c}</span>
                    </li>
                  ))}
                </ol>
              </Card>
            </div>
          </div>

          <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
            <Card className="p-5">
              <p className="text-sm text-ink-3">Bid submission</p>
              <div className="mt-1">
                <ClosingBadge closes={t.closes_at} published={t.published_at} />
              </div>
              <p className="mt-2 text-sm text-ink-2">{formatDate(t.closes_at)}</p>
              <a
                href="https://eprocure.gov.in/eprocure/app"
                target="_blank"
                rel="noreferrer"
                className="mt-5 inline-flex h-11 w-full items-center justify-center gap-2 rounded-full bg-brand text-sm font-semibold text-brand-ink hover:brightness-110"
              >
                Open official portal <ExternalLink className="size-4" />
              </a>
              <p className="mt-3 text-xs text-ink-3">
                Portal links expire with your session, so search the portal for Tender ID <span className="font-mono">{t.source_tender_id}</span>. Download documents and bid there.
              </p>
            </Card>
            <Card className="p-5">
              <p className="flex items-center gap-2 font-semibold text-ink">
                <Bell className="size-4 text-brand" /> Get more like this
              </p>
              <p className="mt-1 text-sm text-ink-2">Email me when a new {sectorMeta(t.sector).label.toLowerCase()} tender opens in {t.state || "India"}.</p>
              <Link
                to={`/alerts?${new URLSearchParams({ ...(t.state ? { state: t.state } : {}), sector: t.sector })}`}
                className="mt-4 inline-flex h-10 w-full items-center justify-center rounded-full border border-line text-sm font-semibold text-ink hover:bg-surface-2"
              >
                Create alert
              </Link>
            </Card>
          </aside>
        </div>
      )}

      {(similar.data?.length ?? 0) > 0 && (
        <section className="mt-14">
          <h2 className="mb-4 text-xl font-bold tracking-tight text-ink">Similar open tenders</h2>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {similar.data!.map((s) => (
              <TenderCard key={s.id} t={s} compact />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
