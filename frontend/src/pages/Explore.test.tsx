import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UpgradeDialogHost } from "../components/Upgrade";
import { PLANS, TENDER, workspace } from "../test/fixtures";
import { mockFetch, renderPage, reply, SIGNED_IN } from "../test/render";
import Explore from "./Explore";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const PAGE = {
  count: 1,
  next: null,
  previous: null,
  search_backend: "postgres",
  relaxed: false,
  facets: { state: [], sector: [], category: [], value_range: [] },
  results: [TENDER],
};

function routes(csv: unknown) {
  return {
    "GET /api/auth/me": SIGNED_IN,
    "GET /api/config": {},
    "GET /api/tenders": PAGE,
    "GET /api/pipeline": [],
    "GET /api/sources": [],
    "GET /api/workspace": workspace(),
    "GET /api/billing/plans": PLANS,
    "GET /api/export/tenders.csv": csv,
  };
}

async function page(path = "/tenders?state=Chhattisgarh") {
  renderPage(
    <>
      <Explore />
      <UpgradeDialogHost />
    </>,
    path,
  );
  // Exports need a signed-in user: wait until the session has loaded.
  await screen.findByRole("tab", { name: /Recommended for you/ });
}

describe("Explore CSV export", () => {
  it("exports the current filters and says when the file was cut short", async () => {
    const calls = mockFetch(
      routes(
        reply(200, "id,title\n42,Resurfacing of NH-44\n", {
          "Content-Type": "text/csv",
          "Content-Disposition": 'attachment; filename="tenderlens-tenders-2026-10-06.csv"',
          "X-Total-Count": "12000",
          "X-Export-Truncated": "true",
        }),
      ),
    );
    await page();

    fireEvent.click(await screen.findByRole("button", { name: /Export CSV/ }));
    expect(await screen.findByText(/The export holds the first 10,000 of 12,000 matching tenders/)).toBeTruthy();
    const url = calls.find((c) => c.url.startsWith("/api/export/tenders.csv"))!.url;
    const q = new URLSearchParams(url.split("?")[1]);
    expect(q.get("state")).toBe("Chhattisgarh");
    expect(q.has("closes_after")).toBe(true);
    expect(q.has("page_size")).toBe(false);
  });

  it("opens the one upgrade prompt on 402 quota_exceeded", async () => {
    mockFetch(routes(reply(402, { detail: "Your plan does not include CSV export. Upgrade to use it.", code: "quota_exceeded", limit: "export" })));
    await page();

    fireEvent.click(await screen.findByRole("button", { name: /Export CSV/ }));
    expect(await screen.findByText("CSV export isn't included in your plan.")).toBeTruthy();
    expect(screen.getByText("Your plan does not include CSV export. Upgrade to use it.")).toBeTruthy();
    // The cheapest plan that has it is suggested.
    await waitFor(() => expect(screen.getByText("Pro includes CSV export.")).toBeTruthy());
    expect(screen.getByRole("link", { name: /See plans/, hidden: true }).getAttribute("href")).toBe("/pricing");
  });
});
