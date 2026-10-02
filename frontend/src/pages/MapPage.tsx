import { useQuery } from "@tanstack/react-query";
import { Map as MapIcon, Table } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { IndiaMap } from "../components/IndiaMap";
import { Card, cx, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { formatCount, formatInr } from "../lib/format";
import { SECTORS, SectorIcon, sectorMeta } from "../lib/sectors";
import { StatePanel } from "./Home";

export default function MapPage() {
  const [sector, setSector] = useState("");
  const [metric, setMetric] = useState<"open" | "closing_this_week">("open");
  const [view, setView] = useState<"map" | "table">("map");
  const map = useQuery({ queryKey: ["map", sector], queryFn: () => api.map(sector) });
  const [selected, setSelected] = useState<string>();
  const rows = [...(map.data ?? [])].sort((a, b) => b[metric] - a[metric]);
  const current = selected ?? rows[0]?.state;
  const max = rows[0]?.[metric] ?? 1;

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <h1 className="text-3xl font-bold tracking-tight text-ink">Tender map of India</h1>
      <p className="mt-1 text-ink-2">Open tenders by state. Filter by sector to see where each kind of work is.</p>

      {/* Filters sit in one row above the chart. */}
      <div className="mt-6 flex flex-wrap items-center gap-2">
        <select value={sector} onChange={(e) => setSector(e.target.value)} className="h-10 rounded-full border border-line bg-surface px-4 text-sm text-ink" aria-label="Sector">
          <option value="">All sectors</option>
          {SECTORS.map((s) => (
            <option key={s.slug} value={s.slug}>
              {s.label}
            </option>
          ))}
        </select>
        <div className="flex rounded-full border border-line bg-surface p-0.5 text-sm" role="radiogroup" aria-label="Measure">
          {(["open", "closing_this_week"] as const).map((m) => (
            <button
              key={m}
              role="radio"
              aria-checked={metric === m}
              onClick={() => setMetric(m)}
              className={cx("rounded-full px-3.5 py-1.5 font-medium", metric === m ? "bg-surface-2 text-ink" : "text-ink-3 hover:text-ink")}
            >
              {m === "open" ? "Open tenders" : "Closing in 7 days"}
            </button>
          ))}
        </div>
        <div className="ml-auto flex rounded-full border border-line bg-surface p-0.5 text-sm" role="radiogroup" aria-label="View">
          {(
            [
              ["map", MapIcon, "Map"],
              ["table", Table, "Table"],
            ] as const
          ).map(([v, Icon, label]) => (
            <button
              key={v}
              role="radio"
              aria-checked={view === v}
              onClick={() => setView(v)}
              className={cx("inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 font-medium", view === v ? "bg-surface-2 text-ink" : "text-ink-3 hover:text-ink")}
            >
              <Icon className="size-4" /> {label}
            </button>
          ))}
        </div>
      </div>

      {view === "map" ? (
        <Card className="mt-4 grid gap-8 p-4 sm:p-6 lg:grid-cols-[1.6fr_1fr]">
          <div className="mx-auto w-full max-w-2xl">
            {map.isLoading ? (
              <Skeleton className="aspect-[600/674] w-full rounded-2xl" />
            ) : (
              <IndiaMap data={map.data} metric={metric} selected={current} onSelect={setSelected} loading={map.isFetching} />
            )}
          </div>
          <div className="lg:border-l lg:border-line lg:pl-8">
            {current && <StatePanel state={current} stat={rows.find((r) => r.state === current)} />}
            {sector && (
              <p className="mt-6 inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-3 py-1 text-sm text-brand">
                <SectorIcon slug={sector} /> Showing {sectorMeta(sector).label} only
              </p>
            )}
          </div>
        </Card>
      ) : (
        <Card className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Open tenders by state</caption>
            <thead>
              <tr className="border-b border-line text-left text-ink-3">
                <th className="px-5 py-3 font-medium">State</th>
                <th className="px-5 py-3 text-right font-medium">Open</th>
                <th className="px-5 py-3 text-right font-medium">Closing in 7 days</th>
                <th className="px-5 py-3 text-right font-medium">Disclosed value</th>
                <th className="px-5 py-3 font-medium">Most common work</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.state} className="border-b border-line last:border-0 hover:bg-surface-2">
                  <td className="px-5 py-3">
                    <Link to={`/tenders?state=${encodeURIComponent(r.state)}${sector ? `&sector=${sector}` : ""}`} className="font-medium text-ink hover:text-brand">
                      {r.state}
                    </Link>
                    <div className="mt-1 h-1 rounded-full bg-surface-2">
                      <div className="h-1 rounded-full bg-brand" style={{ width: `${(r[metric] / max) * 100}%` }} />
                    </div>
                  </td>
                  <td className="px-5 py-3 text-right tabular-nums text-ink">{formatCount(r.open)}</td>
                  <td className="px-5 py-3 text-right tabular-nums text-ink-2">{formatCount(r.closing_this_week)}</td>
                  <td className="px-5 py-3 text-right tabular-nums text-ink-2">{formatInr(r.value_inr, { short: true })}</td>
                  <td className="px-5 py-3 text-ink-2">
                    {r.top_sector && (
                      <span className="inline-flex items-center gap-1.5">
                        <SectorIcon slug={r.top_sector} /> {sectorMeta(r.top_sector).label}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
