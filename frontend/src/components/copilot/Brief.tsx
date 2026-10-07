import { useQuery } from "@tanstack/react-query";
import { Check, CircleCheck, CircleHelp, CircleX, ClipboardCopy, FileSearch, FileText, Loader2 } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router";
import { api, type BriefField, type DocScope, type EligibilityCheck, errorMessage } from "../../lib/api";
import { notReady } from "../../lib/copilot";
import { formatDate, formatInr } from "../../lib/format";
import { Button, cx, Skeleton, Tag } from "../ui";
import { CitationChip, CitationQuote } from "./Citation";

/** Labels for brief keys the server reports as missing (found ones carry their own label). */
const BRIEF_LABELS: Record<string, string> = {
  emd: "EMD (bid security)",
  tender_fee: "Tender fee",
  estimated_value: "Estimated value",
  bid_submission_end: "Bid submission ends",
  bid_opening: "Bid opening",
  prebid_meeting: "Pre-bid meeting",
  completion_period: "Completion period",
  bid_validity: "Bid validity",
  min_turnover: "Minimum turnover",
  similar_work: "Similar work experience",
  performance_security: "Performance security",
  liquidated_damages: "Liquidated damages",
  mse_exemption: "MSE exemption",
  documents_required: "Documents required",
};

const scopeKey = (s: DocScope) => ("tender" in s ? `t${s.tender}` : `d${s.document}`);

/** Refetch every 3 s while the server says the document is still being read. */
const pollWhileReading = (q: { state: { error: unknown } }) => (notReady(q.state.error) === "processing" ? 3000 : false);

function briefText(fields: BriefField[]): string {
  return fields
    .map((f) => {
      const value = Array.isArray(f.value) ? f.value.map((v) => `\n  - ${v}`).join("") : f.value;
      return `${f.label}: ${value}${f.page !== null ? ` (${f.filename}, p. ${f.page})` : ""}`;
    })
    .join("\n");
}

function Loading() {
  return (
    <div className="space-y-3" aria-busy="true">
      {Array.from({ length: 5 }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

function Failed({ error }: { error: unknown }) {
  // 400 {detail, status}: the document isn't ready. While it is being read the query polls,
  // so the panel fills in by itself.
  const state = notReady(error);
  if (state === "processing")
    return (
      <p className="flex items-start gap-2 rounded-md border border-line px-3 py-3 text-sm text-ink-2" role="status">
        <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-signal-text" aria-hidden="true" />
        This document is still being read (text, OCR and passages). The brief appears here as soon as it's done.
      </p>
    );
  return (
    <p className="flex items-start gap-2 rounded-md border border-line px-3 py-3 text-sm text-ink-2">
      <FileSearch className="mt-0.5 size-4 shrink-0 text-ink-3" aria-hidden="true" />
      {errorMessage(error, "Couldn't read the documents.")}
    </p>
  );
}

/** The bid brief: the facts a bidder needs, pulled from the documents by rules (no language
 *  model), each with the page it came from. */
export function BriefPanel({ scope }: { scope: DocScope }) {
  const q = useQuery({ queryKey: ["copilot", "brief", scopeKey(scope)], queryFn: () => api.copilot.brief(scope), retry: false, refetchInterval: pollWhileReading });
  const [open, setOpen] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const base = useId();

  if (q.isLoading) return <Loading />;
  if (q.isError) return <Failed error={q.error} />;
  const b = q.data!;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="num text-xs text-ink-3">
          {b.fields.length} found · {b.missing.length} not stated
          {b.documents !== undefined && ` · ${b.documents} document${b.documents === 1 ? "" : "s"}`} · {formatDate(b.generated_at)}
        </p>
        {b.fields.length > 0 && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              navigator.clipboard?.writeText(briefText(b.fields)).then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              })
            }
          >
            {copied ? <Check className="size-3.5 text-good" aria-hidden="true" /> : <ClipboardCopy className="size-3.5" aria-hidden="true" />}
            {copied ? "Copied" : "Copy brief"}
          </Button>
        )}
      </div>
      {b.documents === 0 ? (
        <p className="rounded-md border border-line px-3 py-3 text-sm text-ink-2">
          None of this tender's documents is ready yet. Upload the NIT and corrigenda; the brief fills in once they have been read.
        </p>
      ) : b.fields.length === 0 ? (
        <p className="rounded-md border border-line px-3 py-3 text-sm text-ink-2">
          Nothing could be read from these documents. Scanned pages need OCR; check that the PDF has the tender's notice inviting tenders.
        </p>
      ) : (
        <dl className="divide-y divide-line rounded-md border border-line bg-surface">
          {b.fields.map((f, i) => {
            const id = `${base}-${i}`;
            const isOpen = open === id;
            return (
              <div key={`${f.key}-${i}`} className="grid gap-x-4 gap-y-1.5 px-3.5 py-3 sm:grid-cols-[170px_1fr]">
                <dt className="label pt-0.5">{f.label}</dt>
                <dd className="min-w-0">
                  {Array.isArray(f.value) ? (
                    <ul className="list-disc space-y-0.5 pl-4 text-sm text-ink marker:text-ink-3">
                      {f.value.map((v, j) => (
                        <li key={j}>{v}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm font-medium text-ink">{f.value}</p>
                  )}
                  {f.quote && (
                    <div className="mt-1.5 space-y-2">
                      <CitationChip filename={f.filename} page={f.page} open={isOpen} onToggle={() => setOpen(isOpen ? null : id)} controls={id} />
                      {isOpen && <CitationQuote id={id} quote={f.quote} filename={f.filename} page={f.page} />}
                    </div>
                  )}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
      {b.missing.length > 0 && (
        <p className="mt-3 text-sm text-ink-2">
          <span className="label mr-2">Not stated</span>
          {b.missing.map((k) => BRIEF_LABELS[k] ?? k).join(" · ")}
        </p>
      )}
      <p className="mt-3 text-xs text-ink-3">Read by fixed rules from the documents, not by a language model. Confirm in the original before you bid.</p>
    </div>
  );
}

/** Amounts arrive as rupees (number or Decimal string): show them as lakh/crore. */
function show(v: string | number | null): string {
  if (v === null || v === "") return "—";
  const n = Number(v);
  return Number.isFinite(n) && n >= 1000 ? formatInr(n) : String(v);
}

const CHECK_ICON = {
  pass: <CircleCheck className="size-4 text-good" aria-label="Meets it" />,
  fail: <CircleX className="size-4 text-critical" aria-label="Falls short" />,
  unknown: <CircleHelp className="size-4 text-ink-3" aria-label="Can't tell" />,
};

const VERDICT = {
  eligible: { tone: "good" as const, title: "You appear to qualify", body: "Every requirement we could read is met by your company profile." },
  not_eligible: { tone: "critical" as const, title: "You may not qualify", body: "At least one requirement is above what your profile shows." },
  unknown: { tone: undefined, title: "Not enough to decide", body: "Some requirements, or some of your profile, are missing." },
};

/** The brief's qualification criteria against the workspace's company profile. */
export function EligibilityPanel({ scope }: { scope: DocScope }) {
  const q = useQuery({
    queryKey: ["copilot", "eligibility", scopeKey(scope)],
    queryFn: () => api.copilot.eligibility(scope),
    retry: false,
    refetchInterval: pollWhileReading,
  });

  if (q.isLoading) return <Loading />;
  if (q.isError) return <Failed error={q.error} />;
  const e = q.data!;
  const v = VERDICT[e.verdict] ?? VERDICT.unknown;
  const profileGaps = e.checks.some((c: EligibilityCheck) => c.yours === null || c.yours === "");
  return (
    <div>
      <div
        className={cx(
          "rounded-md border px-4 py-3",
          v.tone === "good" ? "border-good/40 bg-good-soft" : v.tone === "critical" ? "border-critical/40 bg-critical-soft" : "border-line bg-surface-2/60",
        )}
        role="status"
      >
        <p className="font-medium text-ink">{v.title}</p>
        <p className="mt-0.5 text-sm text-ink-2">{v.body}</p>
      </div>
      {e.checks.length > 0 && (
        <ul className="mt-3 divide-y divide-line rounded-md border border-line bg-surface">
          {e.checks.map((c, i) => (
              <li key={`${c.key}-${i}`} className="grid grid-cols-[20px_1fr] gap-x-3 px-3.5 py-3">
                <span className="pt-0.5">{CHECK_ICON[c.status] ?? CHECK_ICON.unknown}</span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink">{c.requirement}</p>
                  <dl className="num mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                    <dt className="text-ink-3">Required</dt>
                    <dd className="text-ink-2">{show(c.required)}</dd>
                    <dt className="text-ink-3">Yours</dt>
                    <dd className={c.status === "fail" ? "text-critical" : "text-ink-2"}>{show(c.yours)}</dd>
                  </dl>
                  {c.note && <p className="mt-1.5 text-xs text-ink-2">{c.note}</p>}
                  {c.source && (
                    <p className="mt-1.5 inline-flex max-w-full items-center gap-1 text-[11.5px] text-ink-3">
                      <FileText className="size-3 shrink-0" aria-hidden="true" />
                      <span className="truncate">{c.source.filename}</span>
                      <span className="num shrink-0">p. {c.source.page}</span>
                    </p>
                  )}
                </div>
              </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-ink-3">
        {profileGaps ? (
          <>
            <Tag className="mr-1.5 h-5">Profile incomplete</Tag>
            Add your turnover, experience and certificates in{" "}
          </>
        ) : (
          "Compared with the company profile in "
        )}
        <Link to="/workspace#profile" className="font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-signal">
          Workspace
        </Link>
        . A guide only: the buyer's evaluation decides.
      </p>
    </div>
  );
}
