import { sseJson } from "./sse";

// --- Tenders (public) ------------------------------------------------------------------

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
  search_backend: "postgres";
  relaxed: boolean;
  facets: { state: Bucket[]; sector: Bucket[]; category: Bucket[]; value_range: Bucket[] };
  results: Tender[];
}

export interface CrawlSummary {
  status: string;
  finished: string | null;
  new: number;
  updated: number;
}

export interface Stats {
  total_tenders: number;
  open_tenders: number;
  closing_this_week: number;
  by_state: { state: string; count: number }[];
  last_crawl: CrawlSummary | null;
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

/** A portal we crawl, with how its last crawl went. */
export interface Source {
  key: string;
  name: string;
  kind: "gepnic" | "gem" | "cppp";
  state: string | null;
  url: string;
  open_tenders: number;
  last_run: CrawlSummary | null;
  enabled: boolean;
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

// --- Copilot ---------------------------------------------------------------------------

export interface TenderLite {
  id: number;
  title: string;
  source_tender_id: string;
}

/** An uploaded tender document. Named so it doesn't shadow the DOM's Document. */
export interface CopilotDocument {
  id: number;
  filename: string;
  pages: number;
  chunks: number;
  status: "processing" | "ready" | "failed";
  error: string;
  ocr_pages: number;
  tender: TenderLite | null;
  created_at: string;
}

export interface BriefField {
  key: string;
  label: string;
  /** documents_required is a list; everything else is the text as the document states it. */
  value: string | string[];
  page: number | null;
  quote: string;
  document_id: number;
  filename: string;
}

export interface Brief {
  fields: BriefField[];
  missing: string[];
  generated_at: string;
}

export interface Passage {
  n: number;
  document_id: number;
  filename: string;
  page: number;
  text: string;
}

export interface Citation {
  n: number;
  document_id: number;
  filename: string;
  page: number;
  quote: string;
}

export type AnswerStatus = "answered" | "abstained" | "rejected" | "no_context" | "error";

export interface AskFinal {
  status: AnswerStatus;
  answer: string;
  citations: Citation[];
  grounding: { unsupported: string[] } | null;
  model: string;
  mode: "llm" | "extractive";
  latency_ms: number;
}

export type AskEvent =
  | { type: "retrieval"; passages: Passage[] }
  | { type: "delta"; text: string }
  | ({ type: "final" } & AskFinal);

export interface AskRequest {
  question: string;
  tender?: number;
  document_ids?: number[];
}

export interface EligibilityCheck {
  key: string;
  requirement: string;
  required: string | number | null;
  yours: string | number | null;
  status: "pass" | "fail" | "unknown";
  source: { document_id: number; filename: string; page: number } | null;
}

export interface Eligibility {
  verdict: "eligible" | "not_eligible" | "unknown";
  checks: EligibilityCheck[];
}

export interface CopilotStatus {
  llm: { available: boolean; model: string };
  embedding_model: string;
  documents: number;
}

/** Scope of a brief or an eligibility check: every ready document of a tender, or one document. */
export type DocScope = { tender: number } | { document: number };

// --- Workspace, pipeline, billing ------------------------------------------------------

export type Role = "owner" | "admin" | "member";
export const LIMIT_KEYS = ["questions_per_month", "documents_per_month", "alerts", "seats", "export", "api"] as const;
export type LimitKey = (typeof LIMIT_KEYS)[number];
/** A number is a cap, null is unlimited, 0 or false is not included, true is included. */
export type LimitValue = number | boolean | null;

export interface Plan {
  code: string;
  name: string;
  /** Whole rupees; null means priced per customer ("talk to us"). */
  price_inr_month: number | null;
  price_inr_year: number | null;
  limits: Partial<Record<LimitKey, LimitValue>>;
  features: string[];
}

export interface CompanyProfile {
  annual_turnover_inr: string | null;
  largest_similar_work_inr: string | null;
  years_in_business: number | null;
  states: string[];
  sectors: string[];
  certifications: string[];
  gstin: string;
}

export interface Workspace {
  id: number;
  name: string;
  slug: string;
  role: Role;
  plan: Plan;
  usage: Partial<Record<string, number>>;
  profile: CompanyProfile;
}

/** PATCH /api/workspace takes the name and the profile fields side by side. */
export type WorkspacePatch = Partial<CompanyProfile> & { name?: string };

export interface Member {
  id: number;
  email: string;
  name: string;
  role: Role;
  joined_at: string;
}

export interface ApiKey {
  id: number;
  name: string;
  /** First characters of the key, enough to tell keys apart. */
  prefix?: string;
  created_at: string;
  last_used_at?: string | null;
}

/** Only the create response carries the secret, and only once. */
export interface NewApiKey extends ApiKey {
  key: string;
}

export interface Invite {
  id?: number;
  email: string;
  role: Role;
  created_at?: string;
  expires_at?: string | null;
}

export const BID_STATUSES = ["watching", "preparing", "submitted", "won", "lost", "dropped"] as const;
export type BidStatus = (typeof BID_STATUSES)[number];

export interface BidTrack {
  id: number;
  tender: Tender;
  status: BidStatus;
  notes: string;
  bid_amount_inr: string | null;
  owner: { id: number; email: string } | null;
  created_at: string;
  updated_at: string;
}

export interface BidTrackPatch {
  status?: BidStatus;
  notes?: string;
  bid_amount_inr?: string | null;
  owner?: number | null;
}

export interface PipelineSummary {
  by_status: Partial<Record<BidStatus, number>>;
  closing_soon: BidTrack[];
  value_inr_in_play: string | number | null;
}

export type Interval = "month" | "year";

export interface Subscription {
  plan: string;
  status: string;
  interval: Interval | null;
  current_period_end: string | null;
  provider: string | null;
}

export type CheckoutResult =
  | { provider: "razorpay"; key_id: string; subscription_id: string }
  | { provider: "fake"; activated: boolean };

// --- Fetch helpers ---------------------------------------------------------------------

/** Error from the API, with DRF's field errors when the request was invalid, and the
 *  `code`/`limit` of a 402 quota error. */
export class ApiError extends Error {
  status: number;
  fields: Record<string, string[]>;
  code?: string;
  limit?: string;
  constructor(status: number, body: unknown) {
    const fields: Record<string, string[]> = {};
    let message = `Request failed (${status})`;
    let code: string | undefined;
    let limit: string | undefined;
    if (body && typeof body === "object") {
      for (const [k, v] of Object.entries(body as Record<string, unknown>)) {
        if (k === "detail" && typeof v === "string") message = v;
        else if (k === "code" && typeof v === "string") code = v;
        else if (k === "limit" && typeof v === "string") limit = v;
        else if (Array.isArray(v)) fields[k] = v.map(String);
      }
      const first = Object.values(fields)[0]?.[0];
      if (message.startsWith("Request failed") && first) message = first;
    }
    super(message);
    this.status = status;
    this.fields = fields;
    this.code = code;
    this.limit = limit;
  }
}

/** A 402 quota error as `{limit, message}` for an upgrade prompt; null for any other error. */
export function quotaExceeded(e: unknown): { limit: string; message: string } | null {
  if (!(e instanceof ApiError) || e.status !== 402) return null;
  if (e.code && e.code !== "quota_exceeded") return null;
  return { limit: e.limit ?? "", message: e.message };
}

/** The message to show for any thrown value. */
export function errorMessage(e: unknown, fallback = "Something went wrong. Please try again."): string {
  if (e instanceof ApiError) return e.status === 0 ? "Couldn't reach the server. Check your connection." : e.message;
  return fallback;
}

export function getCookie(name: string): string {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : "";
}

function headersFor(method: string, json: boolean, accept = "application/json"): Record<string, string> {
  const headers: Record<string, string> = { Accept: accept };
  if (json) headers["Content-Type"] = "application/json";
  // Read the token on every unsafe request: Django rotates it when you sign in.
  if (method !== "GET") headers["X-CSRFToken"] = getCookie("csrftoken");
  return headers;
}

export async function apiFetch<T>(
  url: string,
  init: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  let r: Response;
  try {
    r = await fetch(url, {
      method,
      headers: headersFor(method, init.body !== undefined),
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      credentials: "same-origin",
      signal: init.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, null);
  }
  if (r.status === 204) return undefined as T;
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, body);
  return body as T;
}

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

/** Why a file can't be uploaded to the Copilot, or null when it can. */
export function uploadProblem(file: { name: string; size: number; type: string }): string | null {
  const pdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!pdf) return `${file.name} is not a PDF. Upload the tender's PDF documents.`;
  if (file.size > MAX_UPLOAD_BYTES) return `${file.name} is larger than 25 MB.`;
  if (file.size === 0) return `${file.name} is empty.`;
  return null;
}

/** Multipart upload over XMLHttpRequest, because fetch can't report upload progress. */
function uploadDocument(
  file: File,
  opts: { tender?: number; onProgress?: (fraction: number) => void; signal?: AbortSignal } = {},
): Promise<CopilotDocument> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/copilot/documents");
    for (const [k, v] of Object.entries(headersFor("POST", false))) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && opts.onProgress?.(e.loaded / e.total);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* an HTML error page from a proxy: keep the status */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as CopilotDocument);
      else reject(new ApiError(xhr.status, body));
    };
    xhr.onerror = () => reject(new ApiError(0, null));
    xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    opts.signal?.addEventListener("abort", () => xhr.abort());
    const form = new FormData();
    form.append("file", file);
    if (opts.tender) form.append("tender", String(opts.tender));
    xhr.send(form);
  });
}

/** POST /api/copilot/ask as a stream of events. A server that answers with plain JSON
 *  (?stream=false, or a proxy that buffers) still yields one final event. */
async function* ask(req: AskRequest, signal?: AbortSignal): AsyncGenerator<AskEvent> {
  let r: Response;
  try {
    r = await fetch("/api/copilot/ask", {
      method: "POST",
      headers: headersFor("POST", true, "text/event-stream"),
      body: JSON.stringify(req),
      credentials: "same-origin",
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, null);
  }
  if (!r.ok) throw new ApiError(r.status, await r.json().catch(() => null));
  if (!r.body || !(r.headers.get("content-type") ?? "").includes("text/event-stream")) {
    yield { type: "final", ...((await r.json()) as AskFinal) };
    return;
  }
  yield* sseJson<AskEvent>(r.body);
}

const scopeQuery = (s: DocScope) => ("tender" in s ? `tender=${s.tender}` : `document=${s.document}`);

// --- Explore filters -------------------------------------------------------------------

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

/** The same search, without paging: exports take every matching row. */
function exportParams(f: Filters): URLSearchParams {
  const p = toApiParams({ ...f, page: 1 });
  p.delete("page_size");
  return p;
}

// --- Endpoints -------------------------------------------------------------------------

async function subscription(): Promise<Subscription> {
  const s = await apiFetch<Omit<Subscription, "plan"> & { plan: string | { code: string } }>("/api/billing/subscription");
  return { ...s, plan: typeof s.plan === "string" ? s.plan : s.plan.code };
}

export const api = {
  tenders: (f: Filters, signal?: AbortSignal) => apiFetch<TenderPage>(`/api/tenders?${toApiParams(f)}`, { signal }),
  tender: (id: number) => apiFetch<TenderDetail>(`/api/tenders/${id}`),
  similar: (id: number) => apiFetch<Tender[]>(`/api/tenders/${id}/similar`),
  buyer: (id: number) => apiFetch<Buyer>(`/api/buyers/${id}`),
  stats: () => apiFetch<Stats>("/api/stats"),
  sectors: () => apiFetch<SectorStat[]>("/api/sectors"),
  map: (sector?: string) => apiFetch<StateStat[]>(`/api/map${sector ? `?sector=${encodeURIComponent(sector)}` : ""}`),
  sources: () => apiFetch<Source[]>("/api/sources"),
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

  copilot: {
    documents: (tender?: number) => apiFetch<CopilotDocument[]>(`/api/copilot/documents${tender ? `?tender=${tender}` : ""}`),
    document: (id: number) => apiFetch<CopilotDocument>(`/api/copilot/documents/${id}`),
    upload: uploadDocument,
    deleteDocument: (id: number) => apiFetch<void>(`/api/copilot/documents/${id}`, { method: "DELETE" }),
    brief: (s: DocScope) =>
      apiFetch<Brief>("tender" in s ? `/api/copilot/brief?tender=${s.tender}` : `/api/copilot/documents/${s.document}/brief`),
    ask,
    eligibility: (s: DocScope) => apiFetch<Eligibility>(`/api/copilot/eligibility?${scopeQuery(s)}`),
    status: () => apiFetch<CopilotStatus>("/api/copilot/status"),
  },

  workspace: {
    get: () => apiFetch<Workspace>("/api/workspace"),
    update: (patch: WorkspacePatch) => apiFetch<Workspace>("/api/workspace", { method: "PATCH", body: patch }),
    members: () => apiFetch<Member[]>("/api/workspace/members"),
    removeMember: (id: number) => apiFetch<void>(`/api/workspace/members/${id}`, { method: "DELETE" }),
    invite: (email: string, role: Role) => apiFetch<Invite>("/api/workspace/invites", { method: "POST", body: { email, role } }),
    acceptInvite: (token: string) =>
      apiFetch<Partial<Workspace>>(`/api/workspace/invites/${encodeURIComponent(token)}/accept`, { method: "POST" }),
    apiKeys: () => apiFetch<ApiKey[]>("/api/workspace/api-keys"),
    createApiKey: (name: string) => apiFetch<NewApiKey>("/api/workspace/api-keys", { method: "POST", body: { name } }),
    deleteApiKey: (id: number) => apiFetch<void>(`/api/workspace/api-keys/${id}`, { method: "DELETE" }),
  },

  pipeline: {
    list: (status?: BidStatus) => apiFetch<BidTrack[]>(`/api/pipeline${status ? `?status=${status}` : ""}`),
    track: (tender: number, status?: BidStatus) =>
      apiFetch<BidTrack>("/api/pipeline", { method: "POST", body: status ? { tender, status } : { tender } }),
    update: (id: number, patch: BidTrackPatch) => apiFetch<BidTrack>(`/api/pipeline/${id}`, { method: "PATCH", body: patch }),
    remove: (id: number) => apiFetch<void>(`/api/pipeline/${id}`, { method: "DELETE" }),
    summary: () => apiFetch<PipelineSummary>("/api/pipeline/summary"),
  },

  billing: {
    plans: () => apiFetch<Plan[]>("/api/billing/plans"),
    subscription,
    checkout: (plan: string, interval: Interval) =>
      apiFetch<CheckoutResult>("/api/billing/checkout", { method: "POST", body: { plan, interval } }),
    cancel: () => apiFetch<unknown>("/api/billing/cancel", { method: "POST" }),
  },

  exports: {
    csvUrl: (f: Filters) => `/api/export/tenders.csv?${exportParams(f)}`,
    /** Without filters: the whole public release feed, first page. */
    ocdsUrl: (f?: Filters, page = 1) => {
      const p = f ? exportParams(f) : new URLSearchParams();
      if (page > 1) p.set("page", String(page));
      return `/api/ocds/releases${p.size ? `?${p}` : ""}`;
    },
  },
};
