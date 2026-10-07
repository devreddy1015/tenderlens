import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Plan } from "../lib/api";
import { NO_SUBSCRIPTION, PLANS as FIXTURE_PLANS, PRO as PRO_PLAN, workspace } from "../test/fixtures";
import { mockFetch, renderPage, SIGNED_IN, SIGNED_OUT } from "../test/render";
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

describe("Pricing checkout", () => {
  const owner = () => workspace();
  const subscribed = { plan: PRO_PLAN, status: "active", interval: "month", current_period_end: "2026-11-06T00:00:00Z", provider: "razorpay", cancel_at_period_end: false };

  afterEach(() => {
    delete window.Razorpay;
    vi.restoreAllMocks();
  });

  it("activates the plan at once with the fake provider", async () => {
    let paid = false;
    const calls = mockFetch({
      "GET /api/auth/me": SIGNED_IN,
      "GET /api/config": {},
      "GET /api/billing/plans": FIXTURE_PLANS,
      "GET /api/workspace": () => (paid ? workspace({ plan: PRO_PLAN }) : owner()),
      "GET /api/billing/subscription": () => (paid ? { ...subscribed, provider: "fake" } : NO_SUBSCRIPTION),
      "POST /api/billing/checkout": () => {
        paid = true;
        return { provider: "fake", activated: true };
      },
    });
    renderPage(<Pricing />, "/pricing");

    fireEvent.click(await screen.findByRole("button", { name: /Choose Pro/ }));
    expect(await screen.findByText("You're on the Pro plan.")).toBeTruthy();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ plan: "pro", interval: "month" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Current plan" })).toBeTruthy());
  });

  it("opens Razorpay Checkout and waits for the subscription to turn active", async () => {
    let paid = false;
    const opened: Record<string, unknown>[] = [];
    window.Razorpay = class {
      constructor(private o: { handler: (r: unknown) => void } & Record<string, unknown>) {
        opened.push(o);
      }
      on() {}
      open() {
        // The customer pays; Razorpay's webhook then activates the subscription on our side.
        paid = true;
        setTimeout(() => this.o.handler({ razorpay_payment_id: "pay_1", razorpay_subscription_id: "sub_1", razorpay_signature: "sig" }), 0);
      }
    } as unknown as typeof window.Razorpay;
    mockFetch({
      "GET /api/auth/me": SIGNED_IN,
      "GET /api/config": {},
      "GET /api/billing/plans": FIXTURE_PLANS,
      "GET /api/workspace": () => (paid ? workspace({ plan: PRO_PLAN }) : owner()),
      "GET /api/billing/subscription": () => (paid ? subscribed : NO_SUBSCRIPTION),
      "POST /api/billing/checkout": { provider: "razorpay", key_id: "rzp_test_1", subscription_id: "sub_1", short_url: "https://rzp.io/i/abc" },
    });
    renderPage(<Pricing />, "/pricing");

    fireEvent.click(await screen.findByRole("button", { name: /Choose Pro/ }));
    expect(await screen.findByText("Your new plan is active.")).toBeTruthy();
    expect(opened[0]).toMatchObject({ key: "rzp_test_1", subscription_id: "sub_1", name: "TenderLens", prefill: { email: "a@firm.in" } });
  });

  it("falls back to Razorpay's hosted page when Checkout can't load", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    // The script tag fails to load (blocked, offline).
    vi.spyOn(document.head, "appendChild").mockImplementation((el) => {
      setTimeout(() => (el as HTMLScriptElement).onerror?.(new Event("error")), 0);
      return el;
    });
    mockFetch({
      "GET /api/auth/me": SIGNED_IN,
      "GET /api/config": {},
      "GET /api/billing/plans": FIXTURE_PLANS,
      "GET /api/workspace": owner(),
      "GET /api/billing/subscription": NO_SUBSCRIPTION,
      "POST /api/billing/checkout": { provider: "razorpay", key_id: "rzp_test_1", subscription_id: "sub_1", short_url: "https://rzp.io/i/abc" },
    });
    renderPage(<Pricing />, "/pricing");

    fireEvent.click(await screen.findByRole("button", { name: /Choose Pro/ }));
    await waitFor(() => expect(open).toHaveBeenCalledWith("https://rzp.io/i/abc", "_blank", "noopener"));
    expect(await screen.findByText(/Complete the payment in the Razorpay tab/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Activating/ })).toBeTruthy();
  });

  it("asks members to get an owner to upgrade", async () => {
    mockFetch({
      "GET /api/auth/me": SIGNED_IN,
      "GET /api/config": {},
      "GET /api/billing/plans": FIXTURE_PLANS,
      "GET /api/workspace": workspace({ role: "member" }),
      "GET /api/billing/subscription": NO_SUBSCRIPTION,
    });
    renderPage(<Pricing />, "/pricing");
    const btn = (await screen.findByRole("button", { name: "Ask an owner to upgrade" })) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});
