import { Braces, Check, Copy, KeyRound, ShieldCheck } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link } from "react-router";
import { ButtonLink, Card, PageHeader, Tag } from "../components/ui";
import { MAX_CSV_ROWS } from "../lib/api";
import { formatCount } from "../lib/format";

function Code({ children, label }: { children: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative">
      <pre className="num overflow-x-auto rounded-md border border-line bg-surface-2/60 p-4 pr-12 text-[12.5px] leading-relaxed text-ink-2" aria-label={label}>
        {children}
      </pre>
      <button
        type="button"
        onClick={() =>
          navigator.clipboard?.writeText(children).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          })
        }
        className="absolute top-2 right-2 grid size-8 place-items-center rounded-md text-ink-3 hover:bg-surface hover:text-ink"
        aria-label={`Copy: ${label}`}
      >
        {copied ? <Check className="size-4 text-good" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}
      </button>
    </div>
  );
}

function H2({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h2 id={id} className="scroll-mt-24 text-xl font-semibold text-ink">
      {children}
    </h2>
  );
}

type Access = "public" | "key" | "export";
const ACCESS: Record<Access, { label: string; tone?: "signal" | "good" }> = {
  public: { label: "Public", tone: "good" },
  key: { label: "API key" },
  export: { label: "Key + export", tone: "signal" },
};

const ENDPOINTS: { method: string; path: string; what: string; access: Access }[] = [
  { method: "GET", path: "/api/tenders", what: "Search open tenders: q, state, sector, category, pin, buyer, min_value, max_value, closes_after, sort, page, page_size. Facets included.", access: "public" },
  { method: "GET", path: "/api/tenders/{id}", what: "One tender with its buyer, dates, fees and the portal it came from.", access: "public" },
  { method: "GET", path: "/api/tenders/{id}/similar", what: "Open tenders like this one.", access: "public" },
  { method: "GET", path: "/api/sources", what: "Every portal we crawl, with open tenders and its last successful crawl.", access: "public" },
  { method: "GET", path: "/api/stats · /api/sectors · /api/map", what: "Totals, per sector and per state.", access: "public" },
  { method: "GET", path: "/api/ocds/releases", what: "OCDS 1.1 release package of the same search; 100 per page, links.next / links.prev.", access: "public" },
  { method: "GET", path: "/api/recommendations", what: "Open tenders matched to your company profile, each with its reasons.", access: "key" },
  { method: "GET POST", path: "/api/pipeline", what: "Your bid pipeline; POST {tender, status?} tracks a tender (idempotent).", access: "key" },
  { method: "PATCH DELETE", path: "/api/pipeline/{id}", what: "Move a bid (status), set notes, bid_amount_inr, owner.", access: "key" },
  { method: "GET", path: "/api/pipeline/summary", what: "Counts by status, closing in 7 days, value in play.", access: "key" },
  { method: "GET", path: "/api/export/tenders.csv", what: `The search as CSV, up to ${formatCount(MAX_CSV_ROWS)} rows. X-Total-Count, X-Export-Truncated headers.`, access: "export" },
  { method: "POST", path: "/api/copilot/documents · /ask", what: "Upload tender PDFs; ask questions answered with page citations (SSE or ?stream=false).", access: "key" },
];

const OCDS_SAMPLE = `{
  "version": "1.1",
  "publisher": { "name": "TenderLens" },
  "links": { "next": "…/api/ocds/releases?state=Odisha&page=2" },
  "releases": [{
    "ocid": "ocds-tenderlens-central-2026_CRPF_927478_1",
    "tag": ["tender"],
    "buyer": { "id": "buyer-635", "name": "DG,CRPF,MHA || Jammu Sector,CRPF,MHA" },
    "tender": {
      "id": "2026_CRPF_927478_1",
      "title": "Repair and maintenance of 240 Mens Barrack No. 1 (Outer Portion).",
      "tenderPeriod": { "startDate": "2026-09-24T03:30:00+00:00", "endDate": "2026-10-02T03:30:00+00:00" },
      "value": { "amount": 499469.0, "currency": "INR" },
      "documents": [{ "documentType": "tenderNotice", "url": "https://eprocure.gov.in/…" }]
    }
  }]
}`;

/** /developers: how to use the REST API, API keys and the public OCDS feed. */
export default function Developers() {
  const origin = typeof window !== "undefined" ? window.location.origin : "https://tenderlens.in";
  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <PageHeader
        kicker="Developers"
        title="The tender index as an API"
        actions={
          <>
            <a href="/api/docs/" className="btn btn-secondary btn-md">
              <Braces className="size-4" aria-hidden="true" /> API reference
            </a>
            <ButtonLink to="/workspace#api" variant="primary">
              <KeyRound className="size-4" aria-hidden="true" /> Create a key
            </ButtonLink>
          </>
        }
      >
        Everything in the app is plain JSON over HTTPS: search, recommendations, your bid pipeline and the Copilot. Tender data is also published as Open
        Contracting (OCDS) for anyone, no key needed.
      </PageHeader>

      <nav aria-label="On this page" className="mt-6 flex flex-wrap gap-1 text-sm">
        {[
          ["keys", "API keys"],
          ["endpoints", "Endpoints"],
          ["ocds", "Open data (OCDS)"],
          ["rules", "Limits and attribution"],
        ].map(([id, label]) => (
          <a key={id} href={`#${id}`} className="rounded-md px-2.5 py-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink">
            {label}
          </a>
        ))}
      </nav>

      <section className="mt-10 space-y-4" aria-labelledby="keys">
        <H2 id="keys">API keys</H2>
        <p className="text-ink-2">
          Owners and admins create keys in{" "}
          <Link to="/workspace#api" className="font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-signal">
            Workspace → API keys
          </Link>{" "}
          (the API comes with the Enterprise plan; see{" "}
          <Link to="/pricing" className="font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-signal">
            pricing
          </Link>
          ). The key is shown once. Send it in the <code className="num text-ink">Authorization</code> header:
        </p>
        <Code label="Search with an API key">{`curl -H "Authorization: Api-Key tl_your_key" \\
  "${origin}/api/recommendations?page=1"`}</Code>
        <ul className="space-y-1.5 text-sm text-ink-2">
          <li className="flex gap-2">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-good" aria-hidden="true" /> A key acts as the person who created it, inside that workspace. It
            stops working when they leave or when the plan no longer includes the API.
          </li>
          <li className="flex gap-2">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-good" aria-hidden="true" /> Keys can't manage the workspace, members, invites, keys or billing.
            Revoke a key from the Workspace page at any time.
          </li>
          <li className="flex gap-2">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-good" aria-hidden="true" />
            {/* One flex item: bare text and <code> siblings would each become a column. */}
            <span className="min-w-0 break-words">
              Errors use one shape: <code className="num">{`{"detail": "…"}`}</code>; a plan limit is HTTP 402 with{" "}
              <code className="num">{`"code": "quota_exceeded", "limit": "<key>"`}</code>.
            </span>
          </li>
        </ul>
      </section>

      <section className="mt-14" aria-labelledby="endpoints">
        <H2 id="endpoints">Main endpoints</H2>
        <Card className="mt-4 overflow-hidden">
          <ul className="divide-y divide-line">
            {ENDPOINTS.map((e) => (
              <li key={e.path} className="grid gap-x-5 gap-y-1.5 px-4 py-3.5 sm:grid-cols-[minmax(0,260px)_1fr_auto] sm:px-5">
                <p className="num min-w-0 text-[13px] break-words text-ink">
                  <span className="mr-2 text-[11px] text-signal-text">{e.method}</span>
                  {e.path}
                </p>
                <p className="text-sm text-ink-2">{e.what}</p>
                <div>
                  <Tag tone={ACCESS[e.access].tone} className="h-5 px-1.5 text-[11px]">
                    {ACCESS[e.access].label}
                  </Tag>
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <p className="mt-3 text-sm text-ink-2">
          Lists are paginated as <code className="num">{`{count, next, previous, results}`}</code>. The filters are the ones in the Explore page's address bar.
        </p>
      </section>

      <section className="mt-14 space-y-4" aria-labelledby="ocds">
        <H2 id="ocds">Open data: OCDS releases</H2>
        <p className="text-ink-2">
          <code className="num text-ink">GET /api/ocds/releases</code> is public and takes the same filters as search. Each tender is an Open Contracting Data
          Standard 1.1 release with an <code className="num">ocid</code>, the buyer, the tender period and value, and a link to the source portal, so it loads
          into the same tools as the UK's Contracts Finder or the EU's TED. <code className="num">X-Total-Count</code> has the number of matching tenders.
        </p>
        <Code label="Fetch open Odisha road tenders as OCDS">{`curl "${origin}/api/ocds/releases?state=Odisha&sector=roads&page_size=50"`}</Code>
        <Code label="Example OCDS release package">{OCDS_SAMPLE}</Code>
      </section>

      <section className="mt-14 space-y-3" aria-labelledby="rules">
        <H2 id="rules">Limits and attribution</H2>
        <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2 marker:text-ink-3">
          <li>Rate limits by default: 120 requests a minute without a key, 600 with one. Over the limit you get HTTP 429 with Retry-After.</li>
          <li>Copilot questions and document uploads count against the plan's monthly limits, the same as in the app.</li>
          <li>
            Tender data comes from official public portals (see{" "}
            <Link to="/coverage" className="text-ink underline decoration-line-strong underline-offset-4">
              Coverage
            </Link>
            ). Keep the source portal attribution when you show it, and confirm details on the portal before bidding.
          </li>
        </ul>
      </section>
    </div>
  );
}
