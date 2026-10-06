import type { Plan, Source, Tender, Workspace } from "../lib/api";

/** Shapes copied from the real API (dumped on 2026-10-06), trimmed to what the tests read. */

export const TENDER: Tender = {
  id: 42,
  source: "central",
  source_tender_id: "2026_NHAI_1",
  ref_no: "NHAI/1",
  title: "Resurfacing of NH-44",
  buyer: null,
  buyer_raw: "NHAI",
  category: "Works",
  product_category: "Civil Works",
  sector: "roads",
  value_inr: "45000000.00",
  emd_inr: "900000.00",
  published_at: "2026-10-01T05:00:00Z",
  closes_at: "2099-01-01T05:00:00Z",
  state: "Chhattisgarh",
  location: "Raipur",
};

export const FREE: Plan = {
  code: "free",
  name: "Free",
  price_inr_month: 0,
  price_inr_year: 0,
  limits: { alerts: 2, questions_per_month: 20, documents_per_month: 5, seats: 1, export: false, api: false },
  features: [],
};

export const PRO: Plan = {
  code: "pro",
  name: "Pro",
  price_inr_month: 999,
  price_inr_year: 9990,
  limits: { alerts: null, questions_per_month: 300, documents_per_month: 100, seats: 5, export: true, api: false },
  features: ["CSV export"],
};

export const ENTERPRISE: Plan = {
  code: "enterprise",
  name: "Enterprise",
  price_inr_month: null,
  price_inr_year: null,
  limits: { alerts: null, questions_per_month: null, documents_per_month: null, seats: null, export: true, api: true },
  features: [],
};

export const PLANS = [FREE, PRO, ENTERPRISE];

export function workspace(over: Partial<Workspace> = {}): Workspace {
  return {
    id: 1,
    name: "Asha Infra",
    slug: "asha-infra",
    role: "owner",
    plan: FREE,
    usage: { questions_per_month: 0, documents_per_month: 0, alerts: 0, seats: 1 },
    profile: {
      annual_turnover_inr: "50000000.00",
      largest_similar_work_inr: null,
      years_in_business: null,
      states: ["Chhattisgarh"],
      sectors: ["roads"],
      certifications: [],
      gstin: "",
    },
    calendar_url: "https://tenderlens.in/api/pipeline/calendar.ics?token=abc123",
    ...over,
  };
}

/** GET /api/billing/subscription with no subscription: the server sends the whole Plan. */
export const NO_SUBSCRIPTION = { plan: FREE, status: "none", interval: null, current_period_end: null, provider: null, cancel_at_period_end: false };

export function source(over: Partial<Source> & { key: string }): Source {
  return {
    name: over.key,
    kind: "gepnic",
    state: null,
    url: "https://example.gov.in/nicgep/app",
    open_tenders: 10,
    last_run: { status: "succeeded", finished: "2026-10-06T08:00:00Z", new: 1, updated: 2 },
    last_success: "2026-10-06T08:00:00Z",
    enabled: true,
    ...over,
  };
}
