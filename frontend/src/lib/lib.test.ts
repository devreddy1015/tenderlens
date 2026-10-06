import { describe, expect, it } from "vitest";
import { classBreaks, classOf } from "../components/IndiaMap";
import { DEFAULT_FILTERS, filtersFromParams, filtersToParams, toApiParams } from "./api";
import { closesIn, countdown, formatInr, timeAgo, windowUsed } from "./format";

describe("formatInr", () => {
  it("uses lakh and crore", () => {
    expect(formatInr("800000.00")).toBe("₹8 lakh");
    expect(formatInr("39349000")).toBe("₹3.93 crore");
    expect(formatInr("4918700000.00")).toBe("₹491.87 crore");
    expect(formatInr("16000")).toBe("₹16,000");
    expect(formatInr("4918700000", { short: true })).toBe("₹492 Cr");
  });
  it("treats missing and zero as not disclosed", () => {
    expect(formatInr(null)).toBe("Not disclosed");
    expect(formatInr("0.00")).toBe("Not disclosed");
  });
});

describe("dates", () => {
  const now = new Date("2026-10-02T10:00:00+05:30");
  it("counts down to closing and flags urgency", () => {
    expect(closesIn("2026-10-12T10:00:00+05:30", now)).toEqual({ text: "Closes in 10 days", urgent: false, closed: false });
    expect(closesIn("2026-10-04T10:00:00+05:30", now).urgent).toBe(true);
    expect(closesIn("2026-10-02T15:00:00+05:30", now).text).toBe("Closes in 5h");
    expect(closesIn("2026-10-01T10:00:00+05:30", now).closed).toBe(true);
  });
  it("formats a compact countdown", () => {
    expect(countdown("2026-10-18T14:30:00+05:30", now)).toEqual({ text: "16d 04h", urgent: false, closed: false });
    expect(countdown("2026-10-02T15:07:00+05:30", now)).toEqual({ text: "5h 07m", urgent: true, closed: false });
    expect(countdown("2026-10-05T10:00:00+05:30", now).urgent).toBe(true);
    expect(countdown("2026-10-01T10:00:00+05:30", now).text).toBe("Closed");
    expect(countdown("2026-10-02T10:00:40+05:30", now).text).toBe("< 1m");
  });
  it("time ago and window used", () => {
    expect(timeAgo("2026-10-02T09:35:00+05:30", now)).toBe("25 min ago");
    expect(windowUsed("2026-10-01T10:00:00+05:30", "2026-10-03T10:00:00+05:30", now)).toBeCloseTo(0.5);
  });
});

describe("filters", () => {
  it("round-trips through the URL", () => {
    const f = { ...DEFAULT_FILTERS, q: "road", sector: "roads", state: "Chhattisgarh", pin: "490", sort: "value" as const, page: 3 };
    expect(filtersFromParams(filtersToParams(f))).toEqual(f);
  });
  it("maps to API parameters", () => {
    const now = new Date("2026-10-02T04:30:00Z");
    const p = toApiParams({ ...DEFAULT_FILTERS, q: " road ", value: "1_to_10_crore", pin: "490", sort: "newest" }, now);
    expect(p.get("q")).toBe("road");
    expect(p.get("pin")).toBe("490");
    expect(p.get("min_value")).toBe("10000000");
    expect(p.get("max_value")).toBe("99999999.99");
    expect(p.get("closes_after")).toBe("2026-10-02T04:30:00.000Z");
    expect(p.get("sort")).toBe("newest");
    expect(toApiParams({ ...DEFAULT_FILTERS, includeClosed: true }).has("closes_after")).toBe(false);
  });
});

describe("map classes", () => {
  it("quantile breaks are increasing and every value lands in a class", () => {
    const values = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 389];
    const b = classBreaks(values);
    expect(b.length).toBeGreaterThan(2);
    expect([...b].sort((x, y) => x - y)).toEqual(b);
    for (const v of values) {
      const c = classOf(v, b);
      expect(c).toBeGreaterThanOrEqual(0);
      expect(c).toBeLessThanOrEqual(b.length);
    }
    expect(classOf(0, b)).toBe(-1);
    expect(classOf(389, b)).toBe(b.length);
  });
  it("handles no data", () => {
    expect(classBreaks([])).toEqual([]);
    expect(classBreaks([0, 0])).toEqual([]);
  });
});
