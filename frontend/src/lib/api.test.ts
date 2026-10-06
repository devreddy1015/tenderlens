import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, errorMessage, quotaExceeded } from "./api";

afterEach(() => vi.unstubAllGlobals());

const QUOTA = { detail: "You have used all 20 questions this month.", code: "quota_exceeded", limit: "questions_per_month" };

describe("ApiError", () => {
  it("reads a 402 quota body", () => {
    const e = new ApiError(402, QUOTA);
    expect(e.status).toBe(402);
    expect(e.message).toBe(QUOTA.detail);
    expect(e.code).toBe("quota_exceeded");
    expect(e.limit).toBe("questions_per_month");
    expect(quotaExceeded(e)).toEqual({ limit: "questions_per_month", message: QUOTA.detail });
  });

  it("is not a quota error for other statuses or codes", () => {
    expect(quotaExceeded(new ApiError(403, { detail: "Forbidden" }))).toBeNull();
    expect(quotaExceeded(new ApiError(402, { detail: "x", code: "payment_required" }))).toBeNull();
    expect(quotaExceeded(new Error("boom"))).toBeNull();
  });

  it("uses the first field error when there is no detail", () => {
    const e = new ApiError(400, { email: ["Enter a valid email address."] });
    expect(e.message).toBe("Enter a valid email address.");
    expect(e.fields).toEqual({ email: ["Enter a valid email address."] });
  });

  it("falls back to a generic message for a body that isn't JSON", () => {
    expect(new ApiError(502, null).message).toBe("Request failed (502)");
  });
});

describe("apiFetch", () => {
  it("turns an HTTP 402 into a quota error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(QUOTA), { status: 402 })));
    const e = await apiFetch("/api/copilot/documents").catch((x) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(quotaExceeded(e)?.limit).toBe("questions_per_month");
  });

  it("sends the CSRF token on unsafe requests only", async () => {
    document.cookie = "csrftoken=tok123";
    const f = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", f);
    await apiFetch("/api/pipeline", { method: "POST", body: { tender: 1 } });
    await apiFetch("/api/pipeline");
    const headers = (i: number) => (f.mock.calls[i] as unknown as [string, RequestInit])[1].headers as Record<string, string>;
    expect(headers(0)["X-CSRFToken"]).toBe("tok123");
    expect(headers(1)["X-CSRFToken"]).toBeUndefined();
  });

  it("reports a network failure as status 0", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const e = await apiFetch<never>("/api/stats").catch((x: ApiError) => x);
    expect(e.status).toBe(0);
    expect(errorMessage(e)).toMatch(/Couldn't reach the server/);
  });
});
