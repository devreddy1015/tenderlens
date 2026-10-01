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
  facets: { state: Bucket[]; category: Bucket[]; value_range: Bucket[] };
  results: Tender[];
}

export interface Stats {
  total_tenders: number;
  open_tenders: number;
  closing_this_week: number;
  last_crawl: { finished: string | null; status: string; new: number; updated: number } | null;
}

export interface Buyer {
  id: number;
  canonical_name: string;
  aliases: { alias: string; method: string; score: number }[];
  tender_count: number;
  open_tender_count: number;
  total_value_inr: string | null;
}

export interface Query {
  q: string;
  state: string;
  category: string;
  value_range: string;
  buyer: string;
  open_only: boolean;
  page: number;
}

export const VALUE_RANGES: Record<string, { label: string; min?: number; max?: number }> = {
  under_10_lakh: { label: "Under ₹10 lakh", max: 1_000_000 },
  "10_lakh_to_1_crore": { label: "₹10 lakh – 1 crore", min: 1_000_000, max: 10_000_000 },
  "1_to_10_crore": { label: "₹1 – 10 crore", min: 10_000_000, max: 100_000_000 },
  over_10_crore: { label: "Over ₹10 crore", min: 100_000_000 },
};

export const PAGE_SIZE = 20;

export function toSearchParams(q: Query, now: Date = new Date()): URLSearchParams {
  const p = new URLSearchParams();
  if (q.q.trim()) p.set("q", q.q.trim());
  if (q.state) p.set("state", q.state);
  if (q.category) p.set("category", q.category);
  if (q.buyer) p.set("buyer", q.buyer);
  const range = VALUE_RANGES[q.value_range];
  if (range?.min !== undefined) p.set("min_value", String(range.min));
  // Ranges are half-open [min, max); the API's max_value is inclusive.
  if (range?.max !== undefined) p.set("max_value", String(range.max - 0.01));
  if (q.open_only) p.set("closes_after", now.toISOString());
  if (q.page > 1) p.set("page", String(q.page));
  p.set("page_size", String(PAGE_SIZE));
  return p;
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(url, { signal, headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

export const api = {
  tenders: (q: Query, signal?: AbortSignal) =>
    getJson<TenderPage>(`/api/tenders?${toSearchParams(q)}`, signal),
  tender: (id: number) => getJson<TenderDetail>(`/api/tenders/${id}`),
  buyer: (id: number) => getJson<Buyer>(`/api/buyers/${id}`),
  stats: () => getJson<Stats>("/api/stats"),
};
