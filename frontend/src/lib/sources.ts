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
