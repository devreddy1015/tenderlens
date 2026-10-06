import { describe, expect, it } from "vitest";
import type { Plan } from "./api";
import { formatBytes, formatCount, formatDate, formatInr, formatRupees } from "./format";
import { byPrice, describeLimit, meter, perMonth, priceFor, yearlySaving } from "./plans";

describe("money", () => {
  it("writes exact rupees with Indian grouping", () => {
    expect(formatRupees(119880)).toBe("₹1,19,880");
    expect(formatRupees("4500000.00")).toBe("₹45,00,000");
    expect(formatRupees(null)).toBe("—");
    expect(formatRupees("abc")).toBe("—");
  });
  it("abbreviates to lakh and crore", () => {
    expect(formatInr(250000)).toBe("₹2.5 lakh");
    expect(formatInr(99999)).toBe("₹99,999");
    expect(formatInr(12_50_00_000, { short: true })).toBe("₹12.5 Cr");
  });
  it("counts and sizes", () => {
    expect(formatCount(2712)).toBe("2,712");
    expect(formatCount(1234567)).toBe("12,34,567");
    expect(formatCount(undefined)).toBe("0");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(25 * 1024 * 1024)).toBe("25 MB");
  });
});

describe("formatDate", () => {
  it("shows Indian Standard Time whatever the browser's zone", () => {
    // 18:30 UTC is midnight in India: the date rolls over.
    const s = formatDate("2026-03-31T18:30:00Z");
    expect(s).toMatch(/01 Apr 2026/);
    expect(s).toMatch(/12:00/);
  });
  it("can omit the time and handles missing values", () => {
    expect(formatDate("2026-03-31T18:30:00Z", false)).toBe("01 Apr 2026");
    expect(formatDate(null)).toBe("—");
  });
});

const plan = (code: string, month: number | null, year: number | null): Plan => ({
  code,
  name: code,
  price_inr_month: month,
  price_inr_year: year,
  limits: {},
  features: [],
});

describe("plans", () => {
  const pro = plan("pro", 999, 9990);
  it("prices per interval", () => {
    expect(priceFor(pro, "month")).toBe(999);
    expect(priceFor(pro, "year")).toBe(9990);
    expect(perMonth(pro, "year")).toBe(832);
    expect(priceFor(plan("ent", null, null), "year")).toBeNull();
  });
  it("computes the yearly saving", () => {
    expect(yearlySaving(pro)).toBe(17);
    expect(yearlySaving(plan("free", 0, 0))).toBe(0);
    expect(yearlySaving(plan("odd", 100, 1500))).toBe(0);
  });
  it("describes limits and meters", () => {
    expect(describeLimit(null)).toBe("Unlimited");
    expect(describeLimit(true)).toBe("Included");
    expect(describeLimit(0)).toBe("Not included");
    expect(describeLimit(1000)).toBe("1,000");
    expect(meter(5, 20)).toEqual({ fraction: 0.25, text: "5 of 20", full: false });
    expect(meter(20, 20).full).toBe(true);
    expect(meter(3, null).fraction).toBeNull();
  });
  it("sorts custom-priced plans last", () => {
    expect(byPrice([plan("ent", null, null), pro, plan("free", 0, 0)]).map((p) => p.code)).toEqual(["free", "pro", "ent"]);
  });
});
