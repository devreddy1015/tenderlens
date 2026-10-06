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
  /** The newest run whatever its outcome; `finished` is null while it is running. */
  last_run: CrawlSummary | null;
  /** When the newest successful crawl finished: the freshness we promise on /coverage. */
  last_success: string | null;
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
  /** Tender scope only: how many ready documents the brief was read from (0: none yet). */
  documents?: number;
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
  /** Why the check came out this way, e.g. "No turnover requirement was found…". */
  note?: string;
}

export interface Eligibility {
  verdict: "eligible" | "not_eligible" | "unknown";
  checks: EligibilityCheck[];
}

export interface CopilotStatus {
  llm: { available: boolean; model: string };
  embedding_model: string;
  reranker_model?: string | null;
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
  /** This month's counters plus `alerts` (the team's alerts) and `seats` (members). */
  usage: Partial<Record<string, number>>;
  profile: CompanyProfile;
  /** iCal feed of the pipeline's deadlines; the token in it is the only credential. */
  calendar_url: string;
}

/** One organisation the user belongs to, for the workspace switcher. */
export interface WorkspaceRef {
  id: number;
  name: string;
  slug: string;
  role: Role;
  active: boolean;
}

/** PATCH /api/workspace takes the name and the profile fields side by side. */
export type WorkspacePatch = Partial<CompanyProfile> & { name?: string };

export interface Member {
  /** The membership id (DELETE/PATCH members/{id}); `user_id` is the person (pipeline owner). */
  id: number;
  user_id: number;
  email: string;
  name: string;
  role: Role;
  joined_at: string;
}

export interface ApiKey {
  id: number;
  name: string;
  /** First characters of the key, enough to tell keys apart. */
  prefix: string;
  /** Email of the person who created it; the key acts as them. */
  created_by: string | null;
  created_at: string;
  last_used_at: string | null;
}

/** Only the create response carries the secret, and only once. */
export interface NewApiKey extends ApiKey {
  key: string;
}

export interface Invite {
  id: number;
  email: string;
  role: Role;
  created_at: string;
  expires_at: string;
}

/** GET /api/workspace/invites/{token} (public): what the /invite page shows before joining. */
export interface InvitePreview {
  organization: string;
  email: string;
  role: Role;
  expires_at: string;
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
  /** Decimal string, e.g. "31545007.00". */
  value_inr_in_play: string;
}

export interface RecommendedTender extends Tender {
  /** Why it matched, e.g. "Sector: Roads", "State: Chhattisgarh", "Within your turnover limit". */
  reasons: string[];
}

export interface RecommendationPage {
  count: number;
  next: string | null;
  previous: string | null;
  /** True when the company profile has no states or sectors yet: results are then empty. */
  profile_incomplete: boolean;
  results: RecommendedTender[];
}

export type Interval = "month" | "year";

export type SubscriptionStatus = "none" | "created" | "active" | "pending" | "halted" | "cancelled" | "completed";

/** GET /api/billing/subscription, with `plan` flattened to its code (the server sends the Plan). */
export interface Subscription {
  plan: string;
  status: SubscriptionStatus | string;
  interval: Interval | null;
  current_period_end: string | null;
  provider: string | null;
  /** Razorpay: cancelled, but paid up until current_period_end. */
  cancel_at_period_end: boolean;
}

export type CheckoutResult =
  | { provider: "razorpay"; key_id: string; subscription_id: string; short_url?: string | null }
  | { provider: "fake"; activated: boolean };

export interface CsvExport {
  /** Every matching row, even beyond the export cap. */
  total: number;
  /** True when only the first 10,000 rows were exported. */
  truncated: boolean;
  rows: number;
}

// --- Fetch helpers ---------------------------------------------------------------------

/** Error from the API, with DRF's field errors when the request was invalid, and the
 *  `code`/`limit` of a 402 quota error. */
export class ApiError extends Error {
  status: number;
  fields: Record<string, string[]>;
  code?: string;
  limit?: string;
  /** The parsed JSON body, for extras such as the Copilot's 400 `{detail, status}`. */
  body: Record<string, unknown>;
  constructor(status: number, body: unknown) {
    const fields: Record<string, string[]> = {};
    let message = `Request failed (${status})`;
    let code: string | undefined;
    let limit: string | undefined;
    const raw = body && typeof body === "object" && !Array.isArray(body) ? (body as Record<string, unknown>) : {};
    // DRF sends field errors as lists, but a ValidationError raised with a dict of plain
    // strings (e.g. the Copilot's {"file": "Only PDF files…"}) keeps them as strings.
    const list = (v: unknown) => (Array.isArray(v) ? v.map(String) : typeof v === "string" ? [v] : null);
    for (const [k, v] of Object.entries(raw)) {
      if (k === "detail") {
        const d = list(v)?.[0];
        if (d) message = d;
      } else if (k === "code" && typeof v === "string") code = v;
      else if (k === "limit" && typeof v === "string") limit = v;
      else {
        const l = list(v);
        if (l) fields[k] = l;
      }
    }
    const first = Object.values(fields)[0]?.[0];
    if (message.startsWith("Request failed") && first) message = first;
    super(message);
    this.status = status;
    this.fields = fields;
    this.code = code;
    this.limit = limit;
    this.body = raw;
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

type SubscriptionBody = Omit<Subscription, "plan" | "cancel_at_period_end"> & { plan: string | { code: string }; cancel_at_period_end?: boolean };

const flattenSubscription = (s: SubscriptionBody): Subscription => ({
  ...s,
  plan: typeof s.plan === "string" ? s.plan : s.plan.code,
  cancel_at_period_end: !!s.cancel_at_period_end,
});

const subscription = async () => flattenSubscription(await apiFetch<SubscriptionBody>("/api/billing/subscription"));
const cancelSubscription = async () => flattenSubscription(await apiFetch<SubscriptionBody>("/api/billing/cancel", { method: "POST" }));

/** The file name from a Content-Disposition header, if it names one. */
function attachmentName(header: string | null, fallback: string): string {
  return header?.match(/filename="?([^";]+)"?/)?.[1] ?? fallback;
}

/** GET the CSV export and hand it to the browser as a download. Fetched (not a plain link)
 *  so a 402 can open the upgrade prompt and the truncation header can be read. */
async function downloadCsv(f: Filters): Promise<CsvExport> {
  let r: Response;
  try {
    r = await fetch(`/api/export/tenders.csv?${exportParams(f)}`, { headers: { Accept: "text/csv, application/json" }, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, null);
  }
  if (!r.ok) throw new ApiError(r.status, await r.json().catch(() => null));
  const blob = await r.blob();
  const text = typeof blob.text === "function" ? await blob.text() : "";
  // Rows minus the header line; quoted fields may hold newlines, so this is approximate
  // and only used when X-Total-Count is missing.
  const rows = Math.max(0, text.split("\n").filter(Boolean).length - 1);
  const total = Number(r.headers.get("X-Total-Count") ?? rows);
  const url = URL.createObjectURL?.(blob);
  if (url) {
    const a = document.createElement("a");
    a.href = url;
    a.download = attachmentName(r.headers.get("Content-Disposition"), "tenderlens-tenders.csv");
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  }
  return { total, truncated: r.headers.get("X-Export-Truncated") === "true", rows: Math.min(total, MAX_CSV_ROWS) };
}

export const MAX_CSV_ROWS = 10_000;

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
    /** Owner only. */
    setRole: (id: number, role: Role) => apiFetch<Member>(`/api/workspace/members/${id}`, { method: "PATCH", body: { role } }),
    /** Remove a member; your own membership id means leaving the workspace. */
    removeMember: (id: number) => apiFetch<void>(`/api/workspace/members/${id}`, { method: "DELETE" }),
    invites: () => apiFetch<Invite[]>("/api/workspace/invites"),
    invite: (email: string, role: Role) => apiFetch<Invite>("/api/workspace/invites", { method: "POST", body: { email, role } }),
    revokeInvite: (id: number) => apiFetch<void>(`/api/workspace/invites/${id}`, { method: "DELETE" }),
    invitePreview: (token: string) => apiFetch<InvitePreview>(`/api/workspace/invites/${encodeURIComponent(token)}`),
    acceptInvite: (token: string) => apiFetch<Workspace>(`/api/workspace/invites/${encodeURIComponent(token)}/accept`, { method: "POST" }),
    list: () => apiFetch<WorkspaceRef[]>("/api/workspaces"),
    switchTo: (organization: number) => apiFetch<Workspace>("/api/workspace/switch", { method: "POST", body: { organization } }),
    /** Owner/admin: a new calendar token; the old feed URL stops working. */
    rotateCalendar: () => apiFetch<{ calendar_url: string }>("/api/workspace/calendar-token", { method: "POST" }),
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

  recommendations: (page = 1) => apiFetch<RecommendationPage>(`/api/recommendations?page=${page}&page_size=${PAGE_SIZE}`),

  billing: {
    plans: () => apiFetch<Plan[]>("/api/billing/plans"),
    subscription,
    checkout: (plan: string, interval: Interval) =>
      apiFetch<CheckoutResult>("/api/billing/checkout", { method: "POST", body: { plan, interval } }),
    cancel: cancelSubscription,
  },

  exports: {
    csvUrl: (f: Filters) => `/api/export/tenders.csv?${exportParams(f)}`,
    downloadCsv,
    /** Without filters: the whole public release feed, first page. */
    ocdsUrl: (f?: Filters, page = 1) => {
      const p = f ? exportParams(f) : new URLSearchParams();
      if (page > 1) p.set("page", String(page));
      return `/api/ocds/releases${p.size ? `?${p}` : ""}`;
    },
  },
};
