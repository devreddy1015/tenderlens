import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BidTrack, Tender } from "../lib/api";
import { mockFetch, renderPage, SIGNED_IN } from "../test/render";
import Pipeline from "./Pipeline";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TENDER: Tender = {
  id: 42,
  source: "cppp",
  source_tender_id: "2026_NHAI_1",
  ref_no: "NHAI/1",
  title: "Resurfacing of NH-44",
  buyer: null,
  buyer_raw: "NHAI",
  category: "Works",
  product_category: "Civil Works",
  sector: "roads",
  value_inr: "45000000",
  emd_inr: "900000",
  published_at: "2026-10-01T05:00:00Z",
  closes_at: "2099-01-01T05:00:00Z",
  state: "Madhya Pradesh",
  location: "Bhopal",
};

const TRACK: BidTrack = {
  id: 1,
  tender: TENDER,
  status: "watching",
  notes: "",
  bid_amount_inr: null,
  owner: null,
  created_at: "2026-10-01T05:00:00Z",
  updated_at: "2026-10-01T05:00:00Z",
};

describe("Pipeline", () => {
  it("moves a bid to the next column and saves it", async () => {
    const calls = mockFetch({
      "GET /api/auth/me": SIGNED_IN,
      "GET /api/config": {},
      "GET /api/pipeline": [TRACK],
      "GET /api/pipeline/summary": { by_status: { watching: 1 }, closing_soon: [], value_inr_in_play: "45000000" },
      "GET /api/workspace/members": [],
      "PATCH /api/pipeline/1": (body: unknown) => ({ ...TRACK, ...(body as object), updated_at: "2026-10-02T05:00:00Z" }),
    });
    renderPage(<Pipeline />, "/pipeline");

    const watching = await screen.findByRole("region", { name: "Watching" });
    expect(within(watching).getByText(TENDER.title)).toBeTruthy();

    fireEvent.click(within(watching).getByRole("button", { name: `Move “${TENDER.title}” to Preparing` }));

    // Optimistic: the card moves before the server answers.
    const preparing = screen.getByRole("region", { name: "Preparing" });
    await waitFor(() => expect(within(preparing).getByText(TENDER.title)).toBeTruthy());
    expect(within(screen.getByRole("region", { name: "Watching" })).queryByText(TENDER.title)).toBeNull();

    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(patch.url).toBe("/api/pipeline/1");
    expect(patch.body).toEqual({ status: "preparing" });
  });

  it("asks a signed-out visitor to sign in", async () => {
    mockFetch({ "GET /api/auth/me": { authenticated: false, user: null }, "GET /api/config": {} });
    renderPage(<Pipeline />, "/pipeline");
    expect(await screen.findByText("Sign in to manage your bids")).toBeTruthy();
  });
});
