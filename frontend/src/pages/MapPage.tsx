import { useQuery } from "@tanstack/react-query";
import { Map as MapIcon, Table } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { IndiaMap } from "../components/IndiaMap";
import { StatePanel, TopStates } from "../components/StatePanel";
import { Card, cx, inputClass, PageHeader, Segmented, Skeleton, Tag } from "../components/ui";
import { api } from "../lib/api";
import { formatCount, formatInr } from "../lib/format";
import { SECTORS, SectorIcon, sectorMeta } from "../lib/sectors";

type Metric = "open" | "closing_this_week";

export default function MapPage() {
  const [sector, setSector] = useState("");
  const [metric, setMetric] = useState<Metric>("open");
  const [view, setView] = useState<"map" | "table">("map");
  const map = useQuery({ queryKey: ["map", sector], queryFn: () => api.map(sector) });
  const [selected, setSelected] = useState<string>();
  const rows = [...(map.data ?? [])].sort((a, b) => b[metric] - a[metric]);
  const current = selected ?? rows[0]?.state;
  const max = rows[0]?.[metric] || 1;
  const totalOpen = rows.reduce((s, r) => s + r.open, 0);

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageHeader kicker="Geography" title="Tender map of India">
        Open tenders by state. Filter by sector to see where each kind of work is, or switch to the table to rank every state.
      </PageHeader>

      {/* Filters sit in one row above the chart. */}
      <div className="mt-6 flex flex-wrap items-center gap-2">
        {/* inputClass sets w-full, so the wrapper decides the width. */}
        <div className="w-full sm:w-56">
          <select value={sector} onChange={(e) => setSector(e.target.value)} className={cx(inputClass, "h-9 pr-8")} aria-label="Sector">
            <option value="">All sectors</option>
            {SECTORS.map((s) => (
              <option key={s.slug} value={s.slug}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <Segmented<Metric>
          label="Measure"
          value={metric}
          onChange={setMetric}
          options={[
            { value: "open", label: "Open tenders" },
            { value: "closing_this_week", label: "Closing ≤ 7d" },
          ]}
        />
        <p className="num ml-1 hidden text-xs text-ink-3 sm:block" aria-live="polite">
          {map.data ? `${formatCount(totalOpen)} open · ${rows.filter((r) => r.open > 0).length} states` : ""}
        </p>
        <Segmented<"map" | "table">
          label="View"
          className="ml-auto"
          value={view}
          onChange={setView}
          options={[
            {
              value: "map",
              label: (
                <>
                  <MapIcon className="size-3.5" aria-hidden="true" /> Map
                </>
              ),
            },
            {
              value: "table",
              label: (
                <>
                  <Table className="size-3.5" aria-hidden="true" /> Table
                </>
              ),
            },
          ]}
        />
      </div>

      {view === "map" ? (
        <Card ticks className="mt-4 grid gap-8 p-4 sm:p-6 lg:grid-cols-[1.6fr_1fr]">
          <div className="mx-auto w-full max-w-2xl">
            {map.isLoading ? (
              <Skeleton className="aspect-[600/674] w-full rounded-lg" />
            ) : (
              <IndiaMap data={map.data} metric={metric} selected={current} onSelect={setSelected} loading={map.isFetching} />
            )}
          </div>
          <div className="lg:border-l lg:border-line lg:pl-8">
            {sector && (
              <Tag className="mb-5">
                <SectorIcon slug={sector} className="size-3.5" /> Showing {sectorMeta(sector).label} only
              </Tag>
            )}
            {current ? <StatePanel state={current} stat={rows.find((r) => r.state === current)} /> : <Skeleton className="h-64 w-full" />}
            <TopStates data={map.data} selected={current} onSelect={setSelected} metric={metric} count={8} />
          </div>
        </Card>
      ) : (
        <Card className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <caption className="sr-only">Open tenders by state{sector ? `, ${sectorMeta(sector).label} only` : ""}</caption>
            <thead>
              <tr className="border-b border-line text-left">
                <th className="label w-12 px-5 py-3 font-medium">#</th>
                <th className="label px-5 py-3 font-medium">State</th>
                <th className="label px-5 py-3 text-right font-medium">Open</th>
                <th className="label px-5 py-3 text-right font-medium">Closing ≤ 7d</th>
                <th className="label px-5 py-3 text-right font-medium">Disclosed value</th>
                <th className="label px-5 py-3 font-medium">Most common work</th>
              </tr>
            </thead>
            <tbody>
              {map.isLoading
                ? Array.from({ length: 8 }, (_, i) => (
                    <tr key={i} className="border-b border-line last:border-0">
                      <td className="px-5 py-3.5" colSpan={6}>
                        <Skeleton className="h-4 w-full" />
                      </td>
                    </tr>
                  ))
                : rows.map((r, i) => (
                    <tr key={r.state} className="group border-b border-line transition-colors last:border-0 hover:bg-surface-2/60">
                      <td className="num px-5 py-3 text-xs text-ink-3">{String(i + 1).padStart(2, "0")}</td>
                      <td className="px-5 py-3">
                        <Link
                          to={`/tenders?state=${encodeURIComponent(r.state)}${sector ? `&sector=${sector}` : ""}`}
                          className="font-medium text-ink decoration-line-strong underline-offset-4 hover:underline"
                        >
                          {r.state}
                        </Link>
                        <div className="bar mt-1.5 max-w-48" aria-hidden="true">
                          <span style={{ width: `${Math.max(2, (r[metric] / max) * 100)}%` }} />
                        </div>
                      </td>
                      <td className={cx("num px-5 py-3 text-right", metric === "open" ? "font-medium text-ink" : "text-ink-2")}>{formatCount(r.open)}</td>
                      <td className={cx("num px-5 py-3 text-right", metric === "closing_this_week" ? "font-medium text-ink" : "text-ink-2")}>
                        {formatCount(r.closing_this_week)}
                      </td>
                      <td className="num px-5 py-3 text-right text-ink-2">{formatInr(r.value_inr, { short: true })}</td>
                      <td className="px-5 py-3 text-ink-2">
                        {r.top_sector && (
                          <span className="inline-flex items-center gap-1.5">
                            <SectorIcon slug={r.top_sector} className="size-3.5 text-ink-3" /> {sectorMeta(r.top_sector).label}
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
