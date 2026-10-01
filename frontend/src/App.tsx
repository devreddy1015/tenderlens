import { useEffect, useMemo, useState } from "react";
import {
  api,
  type Bucket,
  type Buyer,
  PAGE_SIZE,
  type Query,
  type Stats,
  type Tender,
  type TenderDetail,
  type TenderPage,
  VALUE_RANGES,
} from "./api";
import { closesIn, formatDate, formatInr } from "./format";

const EMPTY: Query = { q: "", state: "", category: "", value_range: "", buyer: "", open_only: true, page: 1 };

function readUrl(): Query {
  const p = new URLSearchParams(window.location.search);
  return {
    q: p.get("q") ?? "",
    state: p.get("state") ?? "",
    category: p.get("category") ?? "",
    value_range: p.get("value") ?? "",
    buyer: p.get("buyer") ?? "",
    open_only: p.get("all") !== "1",
    page: Math.max(1, Number(p.get("page") ?? 1) || 1),
  };
}

function writeUrl(q: Query) {
  const p = new URLSearchParams();
  if (q.q) p.set("q", q.q);
  if (q.state) p.set("state", q.state);
  if (q.category) p.set("category", q.category);
  if (q.value_range) p.set("value", q.value_range);
  if (q.buyer) p.set("buyer", q.buyer);
  if (!q.open_only) p.set("all", "1");
  if (q.page > 1) p.set("page", String(q.page));
  const qs = p.toString();
  window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function App() {
  const [query, setQuery] = useState<Query>(readUrl);
  const [text, setText] = useState(query.q);
  const debouncedText = useDebounced(text, 300);
  const [page, setPage] = useState<TenderPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [buyer, setBuyer] = useState<Buyer | null>(null);

  const update = (patch: Partial<Query>) => setQuery((q) => ({ ...q, page: 1, ...patch }));

  useEffect(() => {
    if (debouncedText !== query.q) update({ q: debouncedText });
  }, [debouncedText]);

  useEffect(() => {
    writeUrl(query);
    const ctrl = new AbortController();
    setLoading(true);
    api
      .tenders(query, ctrl.signal)
      .then((p) => {
        setPage(p);
        setError(null);
      })
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [query]);

  useEffect(() => {
    api.stats().then(setStats).catch(() => setStats(null));
  }, []);

  useEffect(() => {
    if (!query.buyer) return setBuyer(null);
    api.buyer(Number(query.buyer)).then(setBuyer).catch(() => setBuyer(null));
  }, [query.buyer]);

  const pages = page ? Math.max(1, Math.ceil(page.count / PAGE_SIZE)) : 1;

  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          <span className="logo" aria-hidden>◎</span>
          <div>
            <h1>TenderLens</h1>
            <p>Public Indian government tenders, searchable</p>
          </div>
        </div>
        {stats && (
          <dl className="stats">
            <div><dt>Open tenders</dt><dd>{stats.open_tenders.toLocaleString("en-IN")}</dd></div>
            <div><dt>Closing in 7 days</dt><dd>{stats.closing_this_week.toLocaleString("en-IN")}</dd></div>
            <div>
              <dt>Last crawl</dt>
              <dd className="small">{stats.last_crawl?.finished ? formatDate(stats.last_crawl.finished) : "—"}</dd>
            </div>
          </dl>
        )}
      </header>

      <div className="searchbar">
        <input
          type="search"
          value={text}
          placeholder="Search titles, buyers, locations or a tender ID — typos are fine"
          onChange={(e) => setText(e.target.value)}
          aria-label="Search tenders"
          autoFocus
        />
        <label className="toggle">
          <input type="checkbox" checked={query.open_only} onChange={(e) => update({ open_only: e.target.checked })} />
          Open only
        </label>
      </div>

      <div className="body">
        <aside className="facets" aria-label="Filters">
          <Facet title="State" buckets={page?.facets.state} active={query.state} onPick={(state) => update({ state })} />
          <Facet
            title="Category"
            buckets={page?.facets.category}
            active={query.category}
            onPick={(category) => update({ category })}
          />
          <Facet
            title="Tender value"
            buckets={page?.facets.value_range}
            active={query.value_range}
            label={(k) => VALUE_RANGES[k]?.label ?? k}
            keepZero
            onPick={(value_range) => update({ value_range })}
          />
          {(query.state || query.category || query.value_range || query.buyer || query.q) && (
            <button
              className="link"
              onClick={() => {
                setText("");
                setQuery({ ...EMPTY, open_only: query.open_only });
              }}
            >
              Clear all filters
            </button>
          )}
        </aside>

        <main className="results" aria-busy={loading}>
          {buyer && (
            <div className="buyer-banner">
              <div>
                <strong>{buyer.canonical_name}</strong>
                <span>
                  {buyer.tender_count} tenders · {formatInr(buyer.total_value_inr)} total
                  {buyer.aliases.length > 1 && ` · ${buyer.aliases.length} spellings merged`}
                </span>
                {buyer.aliases.length > 1 && (
                  <ul className="aliases">
                    {buyer.aliases.map((a) => (
                      <li key={a.alias} title={`${a.method}, score ${a.score.toFixed(0)}`}>{a.alias}</li>
                    ))}
                  </ul>
                )}
              </div>
              <button className="link" onClick={() => update({ buyer: "" })}>✕</button>
            </div>
          )}

          <div className="meta">
            {error ? (
              <span className="error">Could not load tenders: {error}</span>
            ) : page ? (
              <span>
                {page.count.toLocaleString("en-IN")} tenders
                <span className="backend" title="Which engine answered this query">via {page.search_backend}</span>
                {page.relaxed && <span className="relaxed">No tender matched every word; showing partial matches</span>}
              </span>
            ) : (
              <span>Loading…</span>
            )}
          </div>

          <ul className="list">
            {page?.results.map((t) => (
              <TenderRow key={t.id} t={t} onOpen={() => setSelected(t.id)} onBuyer={(id) => update({ buyer: String(id) })} />
            ))}
          </ul>
          {page && page.count === 0 && <p className="empty">No tenders match. Try fewer filters.</p>}

          {pages > 1 && (
            <nav className="pager" aria-label="Pages">
              <button disabled={query.page <= 1} onClick={() => setQuery((q) => ({ ...q, page: q.page - 1 }))}>
                ← Previous
              </button>
              <span>
                Page {query.page} of {pages.toLocaleString("en-IN")}
              </span>
              <button disabled={query.page >= pages} onClick={() => setQuery((q) => ({ ...q, page: q.page + 1 }))}>
                Next →
              </button>
            </nav>
          )}
        </main>
      </div>

      {selected !== null && <DetailPanel id={selected} onClose={() => setSelected(null)} />}

      <footer className="foot">
        Data from NIC GePNIC public listings (eprocure.gov.in). Crawled politely at one request per second.
        Always confirm details on the official portal before bidding.
      </footer>
    </div>
  );
}

function Facet(props: {
  title: string;
  buckets: Bucket[] | undefined;
  active: string;
  onPick: (key: string) => void;
  label?: (key: string) => string;
  keepZero?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const buckets = (props.buckets ?? []).filter((b) => props.keepZero || b.count > 0);
  const shown = expanded ? buckets : buckets.slice(0, 8);
  return (
    <section className="facet">
      <h2>{props.title}</h2>
      {buckets.length === 0 && <p className="muted">—</p>}
      <ul>
        {shown.map((b) => (
          <li key={b.key}>
            <button
              className={b.key === props.active ? "on" : ""}
              onClick={() => props.onPick(b.key === props.active ? "" : b.key)}
              aria-pressed={b.key === props.active}
            >
              <span>{props.label ? props.label(b.key) : b.key}</span>
              <span className="count">{b.count.toLocaleString("en-IN")}</span>
            </button>
          </li>
        ))}
      </ul>
      {buckets.length > 8 && (
        <button className="link" onClick={() => setExpanded((e) => !e)}>
          {expanded ? "Show fewer" : `Show all ${buckets.length}`}
        </button>
      )}
    </section>
  );
}

function TenderRow({ t, onOpen, onBuyer }: { t: Tender; onOpen: () => void; onBuyer: (id: number) => void }) {
  const due = useMemo(() => closesIn(t.closes_at), [t.closes_at]);
  return (
    <li className="row">
      <button className="title" onClick={onOpen}>{t.title}</button>
      <div className="sub">
        {t.buyer ? (
          <button className="buyer" onClick={() => onBuyer(t.buyer!.id)} title="All tenders from this buyer">
            {t.buyer.canonical_name}
          </button>
        ) : (
          <span>{t.buyer_raw}</span>
        )}
        {t.state && <span className="chip">{t.state}</span>}
        {t.category && <span className="chip">{t.category}</span>}
      </div>
      <div className="facts">
        <span><b>{formatInr(t.value_inr)}</b> value</span>
        <span>EMD {formatInr(t.emd_inr)}</span>
        <span className={due.urgent ? "urgent" : ""}>{due.text}</span>
        <span className="mono">{t.source_tender_id}</span>
      </div>
    </li>
  );
}

function DetailPanel({ id, onClose }: { id: number; onClose: () => void }) {
  const [t, setT] = useState<TenderDetail | null>(null);
  useEffect(() => {
    api.tender(id).then(setT).catch(() => setT(null));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [id, onClose]);
  return (
    <div className="overlay" onClick={onClose}>
      <aside className="panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Tender details">
        <button className="close" onClick={onClose} aria-label="Close">✕</button>
        {!t ? (
          <p>Loading…</p>
        ) : (
          <>
            <h2>{t.title}</h2>
            <dl className="kv">
              <dt>Tender ID</dt><dd className="mono">{t.source_tender_id}</dd>
              <dt>Reference</dt><dd>{t.ref_no || "—"}</dd>
              <dt>Organisation</dt><dd>{t.org_chain}</dd>
              <dt>Value</dt><dd>{formatInr(t.value_inr)}</dd>
              <dt>EMD</dt><dd>{formatInr(t.emd_inr)}</dd>
              <dt>Tender fee</dt><dd>{formatInr(t.fee_inr)}</dd>
              <dt>Category</dt><dd>{[t.category, t.product_category].filter(Boolean).join(" · ") || "—"}</dd>
              <dt>Type</dt><dd>{t.tender_type || "—"}</dd>
              <dt>Location</dt><dd>{[t.location, t.pincode, t.state].filter(Boolean).join(", ") || "—"}</dd>
              <dt>Published</dt><dd>{formatDate(t.published_at)}</dd>
              <dt>Bid submission closes</dt><dd>{formatDate(t.closes_at)}</dd>
              <dt>Bids open</dt><dd>{formatDate(t.opens_at)}</dd>
              <dt>First seen</dt><dd>{formatDate(t.first_seen)}</dd>
            </dl>
            <p className="muted">
              Portal links are session-bound on GePNIC. To open the official page, search the portal for Tender ID{" "}
              <span className="mono">{t.source_tender_id}</span>.
            </p>
            <a className="btn" href="https://eprocure.gov.in/eprocure/app" target="_blank" rel="noreferrer">
              Open eprocure.gov.in ↗
            </a>
          </>
        )}
      </aside>
    </div>
  );
}
