import { describe, expect, it, vi } from "vitest";
import swSource from "../../public/sw.js?raw";

type FetchHandler = (e: { request: Request; respondWith: (r: unknown) => void }) => void;

/** Runs public/sw.js against a stand-in worker scope and returns its fetch handler. */
function loadWorker(): FetchHandler {
  const handlers: Record<string, FetchHandler> = {};
  const scope = {
    location: new URL("https://tenderlens.in/"),
    addEventListener: (type: string, h: FetchHandler) => (handlers[type] = h),
    skipWaiting: () => Promise.resolve(),
    clients: { claim: () => Promise.resolve() },
  };
  const caches = { open: vi.fn(() => Promise.resolve({ match: vi.fn(), put: vi.fn(), keys: vi.fn(() => []) })), match: vi.fn(), keys: vi.fn(() => []) };
  new Function("self", "caches", "fetch", swSource)(scope, caches, vi.fn(() => new Promise(() => {})));
  return handlers.fetch;
}

function intercepts(handler: FetchHandler, url: string, { mode, ...init }: RequestInit = {}): boolean {
  const respondWith = vi.fn();
  const request = new Request(`https://tenderlens.in${url}`, init);
  // Pages can't construct a navigation request; stand the mode in.
  Object.defineProperty(request, "mode", { value: mode ?? "cors" });
  handler({ request, respondWith });
  return respondWith.mock.calls.length > 0;
}

describe("service worker", () => {
  const handler = loadWorker();

  it("never touches the API, admin, sign-in, Django static files or the Copilot stream", () => {
    for (const url of ["/api/tenders?q=road", "/api/copilot/ask", "/api/pipeline/calendar.ics?token=x", "/admin/", "/accounts/google/login/", "/static/admin/base.css", "/health"])
      expect(intercepts(handler, url), url).toBe(false);
    expect(intercepts(handler, "/tenders", { headers: { Accept: "text/event-stream" } })).toBe(false);
    expect(intercepts(handler, "/assets/index-abc.js", { method: "POST" })).toBe(false);
  });

  it("serves the app shell and hashed bundles", () => {
    expect(intercepts(handler, "/tenders/42", { mode: "navigate" })).toBe(true);
    expect(intercepts(handler, "/assets/index-abc123.js")).toBe(true);
    expect(intercepts(handler, "/icons/icon-192.png")).toBe(true);
  });

  it("leaves other origins alone", () => {
    const respondWith = vi.fn();
    handler({ request: new Request("https://checkout.razorpay.com/v1/checkout.js"), respondWith });
    expect(respondWith).not.toHaveBeenCalled();
  });
});
