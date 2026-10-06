import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router";
import { Card, PageHeader, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { formatCount, formatInr } from "../lib/format";
import { SectorIcon } from "../lib/sectors";

const COLS = "md:grid-cols-[2.25rem_minmax(0,1fr)_88px_104px_112px_150px]";

export default function SectorsPage() {
  const q = useQuery({ queryKey: ["sectors"], queryFn: api.sectors });
  const rows = [...(q.data ?? [])].sort((a, b) => b.open - a.open);
  const total = rows.reduce((s, r) => s + r.open, 0) || 1;

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageHeader kicker="Index" title="Tenders by sector">
        Each tender is sorted by the kind of work, from its title and the portal's own category. Pick a sector to see every open tender of that type.
      </PageHeader>

      <Card className="mt-8 overflow-hidden">
        <div className={`label hidden gap-x-5 border-b border-line px-5 py-2.5 md:grid ${COLS}`} aria-hidden="true">
          <span>#</span>
          <span>Sector</span>
          <span className="text-right">Open</span>
          <span className="text-right">Closing ≤ 7d</span>
          <span className="text-right">Value</span>
          <span>Share of open</span>
        </div>
        <ul>
          {q.isLoading
            ? Array.from({ length: 10 }, (_, i) => (
                <li key={i} className={`grid gap-x-5 gap-y-2 border-b border-line px-5 py-4 last:border-0 ${COLS}`}>
                  <Skeleton className="hidden size-5 md:block" />
                  <div>
                    <Skeleton className="mb-2 h-4 w-48" />
                    <Skeleton className="h-3.5 w-full max-w-md" />
                  </div>
                  <Skeleton className="hidden h-4 md:block" />
                  <Skeleton className="hidden h-4 md:block" />
                  <Skeleton className="hidden h-4 md:block" />
                  <Skeleton className="hidden h-3 md:block" />
                </li>
              ))
            : rows.map((s, i) => {
                const share = s.open / total;
                return (
                  <li key={s.slug} className="border-b border-line last:border-0">
                    <Link
                      to={`/tenders?sector=${s.slug}`}
                      className={`group relative grid items-center gap-x-5 gap-y-3 px-5 py-4 transition-colors hover:bg-surface-2/60 ${COLS}`}
                    >
                      <span className="absolute inset-y-0 left-0 w-0.5 bg-signal opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
                      <span className="num hidden text-xs text-ink-3 md:block">{String(i + 1).padStart(2, "0")}</span>
                      <span className="flex min-w-0 gap-3">
                        <SectorIcon slug={s.slug} className="mt-0.5 size-[18px] shrink-0 text-ink-3 transition-colors group-hover:text-ink" />
                        <span className="min-w-0">
                          <span className="flex items-center gap-1.5 font-medium text-ink">
                            {s.label}
                            <ArrowUpRight className="size-3.5 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
                          </span>
                          {s.description && <span className="mt-0.5 line-clamp-2 block text-sm text-ink-2 md:line-clamp-1">{s.description}</span>}
                        </span>
                      </span>
                      {/* Phones: the three numbers sit in a row under the name. */}
                      <dl className="grid grid-cols-[1fr_1fr_1.3fr] gap-2 border-t border-line pt-3 md:contents [&_dt]:whitespace-nowrap [&_dt]:tracking-[0.06em] md:[&_dt]:tracking-[0.12em]">
                        <div className="md:text-right">
                          <dt className="label md:sr-only">Open</dt>
                          <dd className="num mt-1 text-sm font-medium text-ink md:mt-0 md:text-base">{formatCount(s.open)}</dd>
                        </div>
                        <div className="md:text-right">
                          <dt className="label md:sr-only">Closing ≤ 7d</dt>
                          <dd className="num mt-1 text-sm text-ink-2 md:mt-0 md:text-base">{formatCount(s.closing_this_week)}</dd>
                        </div>
                        <div className="text-right">
                          <dt className="label md:sr-only">Value</dt>
                          <dd className="num mt-1 text-sm whitespace-nowrap text-ink-2 md:mt-0 md:text-base">{formatInr(s.value_inr, { short: true })}</dd>
                        </div>
                      </dl>
                      <span className="hidden items-center gap-3 md:flex">
                        <span className="bar flex-1" aria-hidden="true">
                          <span style={{ width: `${Math.max(2, share * 100)}%` }} />
                        </span>
                        <span className="num w-10 text-right text-xs text-ink-3">{Math.round(share * 100)}%</span>
                      </span>
                    </Link>
                  </li>
                );
              })}
        </ul>
      </Card>
      {q.data && (
        <p className="num mt-3 text-xs text-ink-3">
          {formatCount(total)} open tenders across {rows.filter((r) => r.open > 0).length} sectors. Value counts only tenders that disclose one.
        </p>
      )}
    </div>
  );
}
