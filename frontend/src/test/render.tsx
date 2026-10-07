import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { AuthProvider } from "../lib/auth";
import { createQueryClient } from "../lib/queryClient";
import { ToastProvider } from "../lib/toast";

/** A route table for the mocked backend: "METHOD /path" (query string ignored) → JSON body,
 *  or a function of the request for responses that depend on it. Unknown routes are 404. */
export type Routes = Record<string, unknown | ((body: unknown, url: string) => unknown)>;

/** A non-200 or non-JSON response for a route: `reply(402, {...})`, or a CSV with headers. */
export class Reply {
  constructor(
    public status: number,
    public body: unknown,
    public headers: Record<string, string> = {},
  ) {}
}
export const reply = (status: number, body: unknown, headers?: Record<string, string>) => new Reply(status, body, headers);

export interface Call {
  method: string;
  url: string;
  body: unknown;
}

export function mockFetch(routes: Routes): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ method, url, body });
      const key = `${method} ${url.split("?")[0]}`;
      if (!(key in routes)) return new Response(JSON.stringify({ detail: "Not found." }), { status: 404 });
      const r = routes[key];
      const data = typeof r === "function" ? r(body, url) : r;
      if (data instanceof Reply) {
        const text = typeof data.body === "string" ? data.body : JSON.stringify(data.body);
        return new Response(data.status === 204 ? null : text, { status: data.status, headers: { "Content-Type": "application/json", ...data.headers } });
      }
      return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

export const SIGNED_IN = { authenticated: true, user: { email: "a@firm.in", name: "Asha", picture: "" } };
export const SIGNED_OUT = { authenticated: false, user: null };

/** Render a page with the app's providers, a fresh query cache (no retries) and a router. */
export function renderPage(ui: ReactNode, path = "/") {
  const qc = createQueryClient({ retry: false });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}
