import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiKey } from "../lib/api";
import { ENTERPRISE, NO_SUBSCRIPTION, PLANS, workspace } from "../test/fixtures";
import { mockFetch, renderPage, reply, SIGNED_IN } from "../test/render";
import WorkspacePage from "./Workspace";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const MEMBERS = [{ id: 7, user_id: 3, email: "a@firm.in", name: "Asha", role: "owner", joined_at: "2026-10-01T05:00:00Z" }];
const KEY: ApiKey = { id: 5, name: "ERP sync", prefix: "tl_AbCdEfGh", created_by: "a@firm.in", created_at: "2026-10-06T05:00:00Z", last_used_at: null };
const SECRET = "tl_AbCdEfGhsecretsecretsecretsecretsecret12345";

function routes(over: Record<string, unknown> = {}) {
  return {
    "GET /api/auth/me": SIGNED_IN,
    "GET /api/config": {},
    "GET /api/workspace": workspace({ plan: ENTERPRISE }),
    "GET /api/workspace/members": MEMBERS,
    "GET /api/workspace/invites": [],
    "GET /api/billing/subscription": NO_SUBSCRIPTION,
    "GET /api/billing/plans": PLANS,
    ...over,
  };
}

describe("Workspace API keys", () => {
  it("shows a new key once, then only its prefix", async () => {
    let keys: ApiKey[] = [];
    const calls = mockFetch(
      routes({
        "GET /api/workspace/api-keys": () => keys,
        "POST /api/workspace/api-keys": () => {
          keys = [KEY];
          return reply(201, { ...KEY, key: SECRET });
        },
      }),
    );
    renderPage(<WorkspacePage />, "/workspace");

    expect(await screen.findByText("No keys yet.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("New key name"), { target: { value: "ERP sync" } });
    fireEvent.click(screen.getByRole("button", { name: /Create key/ }));

    expect(await screen.findByText(SECRET)).toBeTruthy();
    expect(screen.getByText(/You won't see it again/)).toBeTruthy();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "ERP sync" });
    // The refetched list carries the prefix, never the secret.
    expect(await screen.findByText(/tl_AbCdEfGh… · created/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "I've stored it safely" }));
    expect(screen.queryByText(SECRET)).toBeNull();
  });

  it("revokes a key after confirming", async () => {
    let keys: ApiKey[] = [KEY];
    const calls = mockFetch(
      routes({
        "GET /api/workspace/api-keys": () => keys,
        "DELETE /api/workspace/api-keys/5": () => {
          keys = [];
          return reply(204, null);
        },
      }),
    );
    renderPage(<WorkspacePage />, "/workspace");

    fireEvent.click(await screen.findByRole("button", { name: "Revoke ERP sync" }));
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    expect(await screen.findByText("No keys yet.")).toBeTruthy();
    expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/workspace/api-keys/5")).toBe(true);
  });

  it("offers an upgrade instead when the plan has no API", async () => {
    const calls = mockFetch(routes({ "GET /api/workspace": workspace() }));
    renderPage(<WorkspacePage />, "/workspace");

    expect(await screen.findByText("API access isn't included in your plan.")).toBeTruthy();
    expect(screen.queryByLabelText("New key name")).toBeNull();
    expect(calls.some((c) => c.url.startsWith("/api/workspace/api-keys"))).toBe(false);
  });
});

describe("Workspace team", () => {
  it("shows the upgrade prompt inline when an invite needs another seat", async () => {
    mockFetch(
      routes({
        "GET /api/workspace": workspace(),
        "POST /api/workspace/invites": reply(402, { detail: "Your plan's limit for seats is reached.", code: "quota_exceeded", limit: "seats" }),
      }),
    );
    renderPage(<WorkspacePage />, "/workspace");

    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "ravi@firm.in" } });
    fireEvent.click(screen.getByRole("button", { name: /Send invite/ }));
    expect(await screen.findByText("You've reached your plan's limit for team seats.")).toBeTruthy();
    await waitFor(() => expect(screen.getByText("Your plan's limit for seats is reached.")).toBeTruthy());
  });
});
