import type { Source } from "./api";

export const KIND_LABEL: Record<Source["kind"], string> = { gepnic: "GePNIC", gem: "GeM", cppp: "CPPP" };

/** A crawl's status word as a tag tone. The crawler writes free-form statuses, so match loosely. */
export function runTone(status: string | undefined): "good" | "critical" | "signal" | undefined {
  const s = (status ?? "").toLowerCase();
  if (/fail|error|block/.test(s)) return "critical";
  if (/run|progress|start|queue/.test(s)) return "signal";
  if (/ok|succe|done|finish|complete/.test(s)) return "good";
  return undefined;
}

/** When the newest crawl across all portals finished (ISO), or undefined. */
export function latestRun(sources: Source[] | undefined): string | undefined {
  return (sources ?? [])
    .map((s) => s.last_run?.finished)
    .filter((x): x is string => !!x)
    .sort()
    .at(-1);
}

/** When the newest successful crawl across all portals finished (ISO), or undefined. */
export function latestSuccess(sources: Source[] | undefined): string | undefined {
  return (sources ?? [])
    .map((s) => s.last_success)
    .filter((x): x is string => !!x)
    .sort()
    .at(-1);
}

/** Hours after which a portal's last successful crawl counts as stale. Incremental crawls
 *  run hourly and full ones nightly, so a day and a half means something is wrong. */
export const STALE_HOURS = 36;

export type Freshness = "fresh" | "stale" | "never";

export function freshness(s: Source, now = Date.now()): Freshness {
  if (!s.last_success) return "never";
  return now - new Date(s.last_success).getTime() > STALE_HOURS * 3_600_000 ? "stale" : "fresh";
}

export interface SourceGroups {
  /** All-India portals: CPPP, central PSUs, defence (no state of their own). */
  central: Source[];
  /** One portal per state or union territory, alphabetical by state. */
  states: Source[];
}

/** Central/PSU portals (most open tenders first) and state portals (by state name). */
export function groupSources(sources: Source[] | undefined): SourceGroups {
  const all = sources ?? [];
  return {
    central: all.filter((s) => !s.state).sort((a, b) => b.open_tenders - a.open_tenders || a.name.localeCompare(b.name)),
    states: all.filter((s) => !!s.state).sort((a, b) => (a.state ?? "").localeCompare(b.state ?? "") || a.name.localeCompare(b.name)),
  };
}
