export interface BuyerRef {
  id: number;
  canonical_name: string;
}

export interface Tender {
  id: number;
  source: string;
  source_tender_id: string;
  ref_no: string;
  title: string;
  buyer: BuyerRef | null;
  buyer_raw: string;
  category: string;
  product_category: string;
  sector: string;
  value_inr: string | null;
  emd_inr: string | null;
  published_at: string;
  closes_at: string;
  state: string;
  location: string;
}

export interface TenderDetail extends Tender {
  org_chain: string;
  tender_type: string;
  fee_inr: string | null;
  opens_at: string | null;
  pincode: string;
  url: string;
  first_seen: string;
  last_seen: string;
}

export interface Bucket {
  key: string;
  count: number;
}

export interface TenderPage {
  count: number;
  next: string | null;
  previous: string | null;
  search_backend: "elasticsearch" | "postgres";
  relaxed: boolean;
  facets: { state: Bucket[]; sector: Bucket[]; category: Bucket[]; value_range: Bucket[] };
  results: Tender[];
}

export interface Stats {
  total_tenders: number;
  open_tenders: number;
  closing_this_week: number;
  by_state: { state: string; count: number }[];
  last_crawl: { finished: string | null; status: string; new: number; updated: number } | null;
}

export interface SectorStat {
  slug: string;
  label: string;
  description: string;
  open: number;
  closing_this_week: number;
  value_inr: string | null;
}

export interface StateStat {
  state: string;
  open: number;
  closing_this_week: number;
  value_inr: string | null;
  top_sector: string | null;
}

export interface Buyer {
  id: number;
  canonical_name: string;
  aliases: { alias: string; method: string; score: number }[];
  tender_count: number;
  open_tender_count: number;
  total_value_inr: string | null;
}

export interface Me {
  authenticated: boolean;
  user: { email: string; name: string; picture: string } | null;
}

export interface SiteConfig {
  google_client_id: string;
  dev_login: boolean;
  sources: { key: string; name: string }[];
}

export interface AlertCriteria {
  states: string[];
  pin_prefixes: string[];
  sectors: string[];
  keywords: string;
  min_value_inr: string | null;
}

export interface Alert extends AlertCriteria {
  id: number;
  name: string;
  active: boolean;
  created_at: string;
  last_sent_at: string | null;
}

export interface AlertPreview {
  count: number;
  sample: Tender[];
}

/** Error from the API, with DRF's field errors when the request was invalid. */
export class ApiError extends Error {
  status: number;
  fields: Record<string, string[]>;
  constructor(status: number, body: unknown) {
    const fields: Record<string, string[]> = {};
    let message = `Request failed (${status})`;
    if (body && typeof body === "object") {
      for (const [k, v] of Object.entries(body as Record<string, unknown>)) {
        if (k === "detail" && typeof v === "string") message = v;
        else if (Array.isArray(v)) fields[k] = v.map(String);
      }
      const first = Object.values(fields)[0]?.[0];
      if (message.startsWith("Request failed") && first) message = first;
    }
    super(message);
    this.status = status;
    this.fields = fields;
  }
}

export function getCookie(name: string): string {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : "";
}

export async function apiFetch<T>(
  url: string,
  init: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  // Read the token on every unsafe request: Django rotates it when you sign in.
  if (method !== "GET") headers["X-CSRFToken"] = getCookie("csrftoken");
  const r = await fetch(url, {
    method,
    headers,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    credentials: "same-origin",
    signal: init.signal,
  });
  if (r.status === 204) return undefined as T;
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, body);
  return body as T;
}

export interface Filters {
  q: string;
  sector: string;
  state: string;
  category: string;
  value: string;
  pin: string;
  buyer: string;
  sort: "relevance" | "closing" | "newest" | "value";
  includeClosed: boolean;
  page: number;
}

export const DEFAULT_FILTERS: Filters = {
  q: "",
  sector: "",
  state: "",
  category: "",
  value: "",
  pin: "",
  buyer: "",
  sort: "relevance",
  includeClosed: false,
  page: 1,
};

export const VALUE_RANGES: Record<string, { label: string; min?: number; max?: number }> = {
  under_10_lakh: { label: "Under ₹10 lakh", max: 1_000_000 },
  "10_lakh_to_1_crore": { label: "₹10 lakh – 1 crore", min: 1_000_000, max: 10_000_000 },
  "1_to_10_crore": { label: "₹1 – 10 crore", min: 10_000_000, max: 100_000_000 },
  over_10_crore: { label: "Over ₹10 crore", min: 100_000_000 },
};

export const PAGE_SIZE = 20;

/** URL query string of the Explore page <-> Filters. */
export function filtersFromParams(p: URLSearchParams): Filters {
  const sort = p.get("sort");
  return {
    q: p.get("q") ?? "",
    sector: p.get("sector") ?? "",
    state: p.get("state") ?? "",
    category: p.get("category") ?? "",
    value: p.get("value") ?? "",
    pin: p.get("pin") ?? "",
    buyer: p.get("buyer") ?? "",
    sort: sort === "closing" || sort === "newest" || sort === "value" ? sort : "relevance",
    includeClosed: p.get("closed") === "1",
    page: Math.max(1, Number(p.get("page") ?? 1) || 1),
  };
}

export function filtersToParams(f: Filters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  if (f.sector) p.set("sector", f.sector);
  if (f.state) p.set("state", f.state);
  if (f.category) p.set("category", f.category);
  if (f.value) p.set("value", f.value);
  if (f.pin) p.set("pin", f.pin);
  if (f.buyer) p.set("buyer", f.buyer);
  if (f.sort !== "relevance") p.set("sort", f.sort);
  if (f.includeClosed) p.set("closed", "1");
  if (f.page > 1) p.set("page", String(f.page));
  return p;
}

/** Filters -> /api/tenders query parameters. */
export function toApiParams(f: Filters, now: Date = new Date()): URLSearchParams {
  const p = new URLSearchParams();
  if (f.q.trim()) p.set("q", f.q.trim());
  for (const k of ["sector", "state", "category", "pin", "buyer"] as const) if (f[k]) p.set(k, f[k]);
  const range = VALUE_RANGES[f.value];
  if (range?.min !== undefined) p.set("min_value", String(range.min));
  // Ranges are half-open [min, max); the API's max_value is inclusive.
  if (range?.max !== undefined) p.set("max_value", String(range.max - 0.01));
  if (!f.includeClosed) p.set("closes_after", now.toISOString());
  if (f.sort !== "relevance") p.set("sort", f.sort);
  if (f.page > 1) p.set("page", String(f.page));
  p.set("page_size", String(PAGE_SIZE));
  return p;
}

export const api = {
  tenders: (f: Filters, signal?: AbortSignal) => apiFetch<TenderPage>(`/api/tenders?${toApiParams(f)}`, { signal }),
  tender: (id: number) => apiFetch<TenderDetail>(`/api/tenders/${id}`),
  similar: (id: number) => apiFetch<Tender[]>(`/api/tenders/${id}/similar`),
  buyer: (id: number) => apiFetch<Buyer>(`/api/buyers/${id}`),
  stats: () => apiFetch<Stats>("/api/stats"),
  sectors: () => apiFetch<SectorStat[]>("/api/sectors"),
  map: (sector?: string) => apiFetch<StateStat[]>(`/api/map${sector ? `?sector=${encodeURIComponent(sector)}` : ""}`),
  config: () => apiFetch<SiteConfig>("/api/config"),
  me: () => apiFetch<Me>("/api/auth/me"),
  googleLogin: (credential: string) => apiFetch<Me>("/api/auth/google", { method: "POST", body: { credential } }),
  devLogin: (email: string, name: string) => apiFetch<Me>("/api/auth/dev-login", { method: "POST", body: { email, name } }),
  logout: () => apiFetch<Me>("/api/auth/logout", { method: "POST" }),
  alerts: () => apiFetch<Alert[]>("/api/alerts"),
  createAlert: (a: Partial<Alert>) => apiFetch<Alert>("/api/alerts", { method: "POST", body: a }),
  updateAlert: (id: number, a: Partial<Alert>) => apiFetch<Alert>(`/api/alerts/${id}`, { method: "PATCH", body: a }),
  deleteAlert: (id: number) => apiFetch<void>(`/api/alerts/${id}`, { method: "DELETE" }),
  testAlert: (id: number) => apiFetch<{ sent_to: string; matching: number }>(`/api/alerts/${id}/test`, { method: "POST" }),
  previewAlert: (c: AlertCriteria) => apiFetch<AlertPreview>("/api/alerts/preview", { method: "POST", body: c }),
  feedback: (body: { kind: string; message?: string; email?: string; page?: string; website?: string }) =>
    apiFetch<{ id: number }>("/api/feedback", { method: "POST", body }),
};
