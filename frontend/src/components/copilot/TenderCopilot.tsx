import { ArrowUpRight, ScanText } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import type { TenderDetail } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useDocuments, useRefreshWhenReady } from "../../lib/copilot";
import { SignInDialog } from "../SignIn";
import { CopyId } from "../TenderCard";
import { Button, Card } from "../ui";
import { DocumentList, UploadDropzone } from "./Documents";
import { ModelStatus, Workbench } from "./Workbench";

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="grid grid-cols-[28px_1fr] gap-x-3">
      <span className="num grid size-7 place-items-center rounded-md border border-line text-xs text-signal-text">{String(n).padStart(2, "0")}</span>
      <div className="min-w-0 pt-1">
        <p className="text-sm font-medium text-ink">{title}</p>
        <div className="mt-1 text-sm text-ink-2">{children}</div>
      </div>
    </li>
  );
}

/** The Copilot on a tender's page. Portals put tender documents behind a CAPTCHA, which we
 *  never bypass, so the bidder downloads them and uploads them here. */
export function TenderCopilot({ tender, portalUrl }: { tender: TenderDetail; portalUrl: string }) {
  const { me } = useAuth();
  const [signIn, setSignIn] = useState(false);
  const docs = useDocuments(tender.id);
  const ready = docs.data?.filter((d) => d.status === "ready") ?? [];
  const has = (docs.data?.length ?? 0) > 0;
  useRefreshWhenReady(ready.length);

  const download = (
    <>
      The portal keeps documents behind a CAPTCHA, which we never bypass. On the{" "}
      <a href={portalUrl} target="_blank" rel="noreferrer" className="font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-signal">
        official portal
      </a>
      , search Tender ID <span className="inline-block [&_button]:text-ink-2"><CopyId id={tender.source_tender_id} /></span>, solve the CAPTCHA and
      download the NIT, BOQ and any corrigenda.
    </>
  );

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
        <h2 className="label flex items-center gap-2">
          <ScanText className="size-3.5 text-signal-text" aria-hidden="true" /> Copilot · read the documents
        </h2>
        {me?.authenticated ? (
          <div className="flex items-center gap-4">
            <ModelStatus />
            <Link to={`/copilot?tender=${tender.id}`} className="inline-flex items-center gap-0.5 text-xs text-ink-2 hover:text-ink">
              Open in Copilot <ArrowUpRight className="size-3.5" aria-hidden="true" />
            </Link>
          </div>
        ) : null}
      </div>
      <div className="p-5">
        {!me?.authenticated ? (
          <>
            <p className="text-sm text-ink-2">
              Get the bid brief (EMD, fees, dates, turnover and experience asked for), check whether you qualify, and ask questions with page
              citations, in minutes instead of an afternoon of reading.
            </p>
            <ol className="mt-5 space-y-4">
              <Step n={1} title="Download the documents">
                {download}
              </Step>
              <Step n={2} title="Upload them here">
                PDFs stay private to your workspace.
              </Step>
              <Step n={3} title="Read the brief, check eligibility, ask">
                Answers come only from the documents, and every number is checked against the page it cites.
              </Step>
            </ol>
            <Button variant="primary" className="mt-6" onClick={() => setSignIn(true)}>
              Sign in to use the Copilot
            </Button>
            <SignInDialog open={signIn} onClose={() => setSignIn(false)} title="Sign in to read this tender's documents">
              Upload the documents once; your team gets the brief, the eligibility check and answers with page citations.
            </SignInDialog>
          </>
        ) : (
          <>
            {!has && !docs.isLoading ? (
              <ol className="mb-5 space-y-4">
                <Step n={1} title="Download the documents">
                  {download}
                </Step>
                <Step n={2} title="Upload them here">
                  <UploadDropzone tender={tender.id} className="mt-2" />
                </Step>
              </ol>
            ) : (
              <div className="mb-6 grid gap-3 md:grid-cols-2">
                <DocumentList docs={docs.data} loading={docs.isLoading} />
                <div>
                  <UploadDropzone tender={tender.id} />
                  <p className="mt-2 text-xs text-ink-3">Missing a corrigendum? Download it from the portal (CAPTCHA) and drop it here.</p>
                </div>
              </div>
            )}
            <Workbench
              scope={{ tender: tender.id }}
              tender={tender.id}
              ready={ready.length > 0}
              scopeHint={has ? "The documents are still being read. The brief fills in as soon as they are ready." : "Upload the tender's documents to get the brief."}
            />
          </>
        )}
      </div>
    </Card>
  );
}
