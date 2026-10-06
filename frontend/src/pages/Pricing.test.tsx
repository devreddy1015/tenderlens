import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Plan } from "../lib/api";
import { mockFetch, renderPage, SIGNED_OUT } from "../test/render";
import Pricing from "./Pricing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const PLANS: Plan[] = [
  { code: "free", name: "Free", price_inr_month: 0, price_inr_year: 0, limits: { alerts: 3, questions_per_month: 20 }, features: [] },
  { code: "pro", name: "Pro", price_inr_month: 999, price_inr_year: 9990, limits: { alerts: null, export: true }, features: ["CSV export"] },
  { code: "enterprise", name: "Enterprise", price_inr_month: null, price_inr_year: null, limits: { api: true }, features: [] },
];

describe("Pricing", () => {
  it("switches every price between monthly and yearly", async () => {
    mockFetch({ "GET /api/auth/me": SIGNED_OUT, "GET /api/config": {}, "GET /api/billing/plans": PLANS });
    renderPage(<Pricing />, "/pricing");

    const price = await screen.findByTestId("price-pro");
    expect(price.textContent).toBe("₹999");
    expect(screen.getByText("Billed monthly · cancel any time")).toBeTruthy();
    expect(screen.getByText("Custom")).toBeTruthy();

    const yearly = screen.getByRole("radio", { name: /Yearly · save 17%/ });
    fireEvent.click(yearly);

    expect(yearly.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("price-pro").textContent).toBe("₹9,990");
    expect(screen.getByText(/₹832 a month, billed yearly/)).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: "Monthly" }));
    expect(screen.getByTestId("price-pro").textContent).toBe("₹999");
  });
});
