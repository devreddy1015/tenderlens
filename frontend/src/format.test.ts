import { describe, expect, it } from "vitest";
import { toSearchParams } from "./api";
import { closesIn, formatInr } from "./format";

describe("formatInr", () => {
  it("uses lakh and crore", () => {
    expect(formatInr("800000.00")).toBe("₹8 lakh");
    expect(formatInr("39349000")).toBe("₹3.93 crore");
    expect(formatInr("4918700000.00")).toBe("₹491.87 crore");
    expect(formatInr("16000")).toBe("₹16,000");
  });
  it("handles missing and zero values", () => {
    expect(formatInr(null)).toBe("—");
    expect(formatInr("0.00")).toBe("Not disclosed");
  });
});

describe("closesIn", () => {
  const now = new Date("2026-10-02T10:00:00+05:30");
  it("counts days and flags urgency", () => {
    expect(closesIn("2026-10-12T10:00:00+05:30", now)).toEqual({ text: "Closes in 10 days", urgent: false });
    expect(closesIn("2026-10-04T10:00:00+05:30", now)).toEqual({ text: "Closes in 2 days", urgent: true });
    expect(closesIn("2026-10-02T15:00:00+05:30", now)).toEqual({ text: "Closes in 5h", urgent: true });
    expect(closesIn("2026-10-01T10:00:00+05:30", now).text).toBe("Closed");
  });
});

describe("toSearchParams", () => {
  it("maps UI state to API parameters", () => {
    const now = new Date("2026-10-02T04:30:00Z");
    const p = toSearchParams(
      { q: " road ", state: "Delhi", category: "", value_range: "1_to_10_crore", buyer: "", open_only: true, page: 2 },
      now,
    );
    expect(p.get("q")).toBe("road");
    expect(p.get("state")).toBe("Delhi");
    expect(p.has("category")).toBe(false);
    expect(p.get("min_value")).toBe("10000000");
    expect(p.get("max_value")).toBe("99999999.99");
    expect(p.get("closes_after")).toBe("2026-10-02T04:30:00.000Z");
    expect(p.get("page")).toBe("2");
  });
});
