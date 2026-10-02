import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { Link } from "react-router";
import { Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { formatCount, formatInr } from "../lib/format";
import { SectorIcon } from "../lib/sectors";

export default function SectorsPage() {
  const q = useQuery({ queryKey: ["sectors"], queryFn: api.sectors });
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <h1 className="text-3xl font-bold tracking-tight text-ink">Tenders by sector</h1>
      <p className="mt-1 max-w-2xl text-ink-2">
        Each tender is sorted by the kind of work from its title and the portal's own category. Pick one to see every open tender of that type.
      </p>
      <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {q.isLoading
          ? Array.from({ length: 12 }, (_, i) => <Skeleton key={i} className="h-40 rounded-2xl" />)
          : q.data?.map((s) => (
              <Link
                key={s.slug}
                to={`/tenders?sector=${s.slug}`}
                className="group flex flex-col rounded-2xl border border-line bg-surface p-5 transition-all hover:-translate-y-0.5 hover:border-brand hover:shadow-lg hover:shadow-black/5"
              >
                <div className="flex items-start justify-between">
                  <span className="grid size-11 place-items-center rounded-xl bg-brand-soft text-brand">
                    <SectorIcon slug={s.slug} className="size-5" />
                  </span>
                  <ArrowRight className="size-5 text-ink-3 transition-transform group-hover:translate-x-0.5 group-hover:text-brand" />
                </div>
                <h2 className="mt-4 text-lg font-semibold text-ink group-hover:text-brand">{s.label}</h2>
                <p className="mt-1 flex-1 text-sm text-ink-2">{s.description}</p>
                <dl className="mt-4 flex gap-6 border-t border-line pt-3 text-sm">
                  <div>
                    <dt className="text-ink-3">Open</dt>
                    <dd className="font-semibold text-ink tabular-nums">{formatCount(s.open)}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-3">Closing this week</dt>
                    <dd className="font-semibold text-ink tabular-nums">{formatCount(s.closing_this_week)}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-3">Value</dt>
                    <dd className="font-semibold text-ink tabular-nums">{formatInr(s.value_inr, { short: true })}</dd>
                  </div>
                </dl>
              </Link>
            ))}
      </div>
    </div>
  );
}
