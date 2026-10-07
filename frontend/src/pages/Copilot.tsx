import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowUpRight, FileStack, Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { DocumentList, UploadDropzone } from "../components/copilot/Documents";
import { ModelStatus, Workbench } from "../components/copilot/Workbench";
import { SignInGate } from "../components/SignIn";
import { Countdown, CopyId } from "../components/TenderCard";
import { UsageMeters } from "../components/UsageMeters";
import { Card, cx, inputClass, PageHeader, Skeleton } from "../components/ui";
import { api, DEFAULT_FILTERS, type DocScope, type TenderLite } from "../lib/api";
import { useDocuments, useRefreshWhenReady } from "../lib/copilot";
import { useDebounced } from "../lib/hooks";
import { usePipeline, usePortalUrl, useSource } from "../lib/queries";

function PanelHead({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
      <h2 className="label">{children}</h2>
      {aside}
    </div>
  );
}

/** Find any tender in the index by words or ID, to attach documents to it. */
function FindTender({ onPick }: { onPick: (id: number) => void }) {
  const [q, setQ] = useState("");
  const term = useDebounced(q.trim(), 300);
  const results = useQuery({
    queryKey: ["tenders", "copilot-find", term],
    queryFn: ({ signal }) => api.tenders({ ...DEFAULT_FILTERS, q: term, includeClosed: true }, signal),
    enabled: term.length >= 2,
    placeholderData: keepPreviousData,
  });
  return (
    <div className="mt-3">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-ink-3" aria-hidden="true" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find another tender by words or ID" aria-label="Find a tender" className={cx(inputClass, "h-9 pl-8 text-[13px]")} />
      </div>
      {term.length >= 2 && (
        <ul className="mt-1.5 max-h-64 overflow-y-auto rounded-md border border-line bg-surface">
          {results.isLoading ? (
            <li className="px-3 py-2.5">
              <Skeleton className="h-4 w-full" />
            </li>
          ) : results.data?.results.length ? (
            results.data.results.slice(0, 8).map((t) => (
              <li key={t.id} className="border-b border-line last:border-0">
                <button
                  type="button"
                  onClick={() => {
                    onPick(t.id);
                    setQ("");
                  }}
                  className="w-full px-3 py-2 text-left hover:bg-surface-2"
                >
                  <span className="line-clamp-2 text-[13px] text-ink">{t.title}</span>
                  <span className="num mt-0.5 block truncate text-[11px] text-ink-3">{t.source_tender_id}</span>
                </button>
              </li>
            ))
          ) : (
            <li className="px-3 py-2.5 text-xs text-ink-3">No tender matches “{term}”.</li>
          )}
        </ul>
      )}
    </div>
  );
}

function TenderPicker({ tenderId, onChange }: { tenderId?: number; onChange: (id?: number) => void }) {
  const pipeline = usePipeline();
  const docs = useDocuments();
  const picked = useQuery({ queryKey: ["tender", tenderId], queryFn: () => api.tender(tenderId!), enabled: !!tenderId });
  const source = useSource(picked.data?.source);
  const portalUrl = usePortalUrl(picked.data?.source);

  // Tenders worth offering: the ones being bid on, and the ones that already have documents.
  const { tracked, withDocs } = useMemo(() => {
    const tracked = new Map<number, TenderLite>((pipeline.data ?? []).map((b) => [b.tender.id, b.tender]));
    const withDocs = new Map<number, TenderLite>();
    for (const d of docs.data ?? []) if (d.tender && !tracked.has(d.tender.id)) withDocs.set(d.tender.id, d.tender);
    return { tracked, withDocs };
  }, [pipeline.data, docs.data]);
  const known = tenderId === undefined || tracked.has(tenderId) || withDocs.has(tenderId);
  const label = (t: TenderLite) => (t.title.length > 70 ? `${t.title.slice(0, 68)}…` : t.title);

  return (
    <Card>
      <PanelHead>Tender</PanelHead>
      <div className="p-4">
        <select value={tenderId ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : undefined)} className={cx(inputClass, "h-9 text-[13px]")} aria-label="Tender">
          <option value="">No tender: pick documents below</option>
          {!known && picked.data && <option value={picked.data.id}>{label(picked.data)}</option>}
          {tracked.size > 0 && (
            <optgroup label="In your pipeline">
              {[...tracked.values()].map((t) => (
                <option key={t.id} value={t.id}>
                  {label(t)}
                </option>
              ))}
            </optgroup>
          )}
          {withDocs.size > 0 && (
            <optgroup label="With uploaded documents">
              {[...withDocs.values()].map((t) => (
                <option key={t.id} value={t.id}>
                  {label(t)}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <FindTender onPick={onChange} />

        {tenderId &&
          (picked.isLoading ? (
            <Skeleton className="mt-4 h-24 w-full" />
          ) : picked.data ? (
            <div className="mt-4 rounded-md border border-line bg-surface-2/50 p-3">
              <div className="flex items-start justify-between gap-2">
                <Link to={`/tenders/${picked.data.id}`} className="line-clamp-3 text-sm leading-snug font-medium text-ink hover:underline">
                  {picked.data.title}
                </Link>
                <button type="button" onClick={() => onChange(undefined)} className="shrink-0 text-ink-3 hover:text-ink" aria-label="Clear tender">
                  <X className="size-4" />
                </button>
              </div>
              <p className="mt-1 line-clamp-1 text-xs text-ink-2">{picked.data.buyer?.canonical_name ?? picked.data.buyer_raw}</p>
              <div className="mt-2 flex items-end justify-between gap-2">
                <span className="-ml-1">
                  <CopyId id={picked.data.source_tender_id} />
                </span>
                <Countdown closes={picked.data.closes_at} compact className="text-right [&>p]:text-[13px]" />
              </div>
              <a
                href={portalUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1 text-xs text-ink-2 underline decoration-line-strong underline-offset-4 hover:text-ink"
              >
                Download documents on {source?.name ?? "the official portal"} <ArrowUpRight className="size-3" aria-hidden="true" />
              </a>
            </div>
          ) : (
            <p className="mt-3 text-xs text-critical">That tender isn't in the index any more.</p>
          ))}
      </div>
    </Card>
  );
}

function CopilotDesk() {
  const [params, setParams] = useSearchParams();
  const tenderId = Number(params.get("tender")) || undefined;
  const docs = useDocuments(tenderId);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const ready = (docs.data ?? []).filter((d) => d.status === "ready");
  useRefreshWhenReady(ready.length);
  const picked = ready.filter((d) => selected.has(d.id));
  const scope: DocScope | null = tenderId ? { tender: tenderId } : picked.length === 1 ? { document: picked[0].id } : null;
  // Without a tender, questions go to the ticked documents, or to every ready one.
  const documentIds = tenderId ? undefined : (picked.length ? picked : ready).map((d) => d.id);

  const pickTender = (id?: number) => {
    setSelected(new Set());
    setParams(id ? { tender: String(id) } : {}, { replace: true });
  };
  const toggle = (id: number) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
      <div className="space-y-4">
        <TenderPicker tenderId={tenderId} onChange={pickTender} />
        <Card>
          <PanelHead aside={docs.data && <span className="num text-xs text-ink-3">{docs.data.length}</span>}>Documents</PanelHead>
          <div className="space-y-3 p-4">
            {tenderId && !docs.isLoading && !docs.data?.length && (
              <p className="text-xs text-ink-2">
                Portals keep tender documents behind a CAPTCHA, which we never bypass. Download the NIT, BOQ and corrigenda from the portal, then drop them here.
              </p>
            )}
            <UploadDropzone tender={tenderId} />
            <DocumentList
              docs={docs.data}
              loading={docs.isLoading}
              selected={tenderId ? undefined : selected}
              onToggle={tenderId ? undefined : toggle}
              showTender={!tenderId}
              empty={tenderId ? "No documents for this tender yet." : "No documents yet. Upload a tender's PDFs to start."}
            />
            {!tenderId && ready.length > 1 && (
              <p className="text-xs text-ink-3">
                {picked.length ? `${picked.length} ticked.` : "None ticked: questions search every ready document."} Tick one for its brief and eligibility.
              </p>
            )}
          </div>
        </Card>
        <Card>
          <PanelHead>This month</PanelHead>
          <div className="p-4">
            <UsageMeters keys={["questions_per_month", "documents_per_month"]} />
            <Link to="/pricing" className="mt-3 inline-block text-xs text-ink-2 underline decoration-line-strong underline-offset-4 hover:text-ink">
              Plans and limits
            </Link>
          </div>
        </Card>
      </div>

      <Card className="min-w-0">
        <PanelHead>Brief · Ask · Eligibility</PanelHead>
        <div className="p-4 sm:p-6">
          <Workbench
            key={tenderId ?? "none"}
            scope={scope}
            tender={tenderId}
            documentIds={documentIds}
            ready={tenderId ? ready.length > 0 : (documentIds?.length ?? 0) > 0}
            scopeHint={
              tenderId
                ? docs.data?.length
                  ? "The documents are still being read. The brief fills in as soon as they are ready."
                  : "Upload this tender's documents to get the brief."
                : ready.length
                  ? "Tick one document on the left for its brief and eligibility, or pick a tender to use all of its documents."
                  : "Upload a tender's documents, or pick a tender, to start."
            }
          />
        </div>
      </Card>
    </div>
  );
}

export default function CopilotPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageHeader kicker="Copilot" title="Read a tender in minutes" actions={<ModelStatus />}>
        Upload a tender's PDFs. Get the bid brief with page citations, check whether your company qualifies, and ask questions answered only from the documents.
      </PageHeader>
      <SignInGate
        title="Sign in to use the Copilot"
        pitch={
          <span className="flex items-start gap-2">
            <FileStack className="mt-0.5 size-4 shrink-0 text-ink-3" aria-hidden="true" />
            Documents stay private to your workspace. Every answer cites the page it came from, and numbers are checked against that page before you see them.
          </span>
        }
      >
        <CopilotDesk />
      </SignInGate>
    </div>
  );
}
