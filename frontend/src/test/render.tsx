import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { AuthProvider } from "../lib/auth";
import { ToastProvider } from "../lib/toast";

/** A route table for the mocked backend: "METHOD /path" (query string ignored) → JSON body,
 *  or a function of the request for responses that depend on it. Unknown routes are 404. */
export type Routes = Record<string, unknown | ((body: unknown, url: string) => unknown)>;

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
      return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

export const SIGNED_IN = { authenticated: true, user: { email: "a@firm.in", name: "Asha", picture: "" } };
export const SIGNED_OUT = { authenticated: false, user: null };

/** Render a page with the app's providers, a fresh query cache (no retries) and a router. */
export function renderPage(ui: ReactNode, path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
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
