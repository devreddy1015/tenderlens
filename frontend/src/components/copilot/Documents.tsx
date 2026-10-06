import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, FileText, Loader2, Trash2, UploadCloud, X } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router";
import { api, type CopilotDocument, errorMessage, quotaExceeded, uploadProblem } from "../../lib/api";
import { formatBytes, formatDate } from "../../lib/format";
import { useToast } from "../../lib/toast";
import { UpgradeNotice } from "../Upgrade";
import { Button, cx, Skeleton, Tag } from "../ui";

interface Upload {
  key: number;
  name: string;
  size: number;
  progress: number;
  state: "uploading" | "done" | "error";
  error?: string;
  quotaLimit?: string;
  abort: AbortController;
}

/** Drop or choose tender PDFs; each uploads with its own progress bar. Reading the PDF
 *  (text, OCR, chunks) happens on the server afterwards, and the list polls for it. */
export function UploadDropzone({ tender, className }: { tender?: number; className?: string }) {
  const qc = useQueryClient();
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const seq = useRef(0);
  const patch = (key: number, p: Partial<Upload>) => setUploads((u) => u.map((x) => (x.key === key ? { ...x, ...p } : x)));
  const drop = (key: number) => setUploads((u) => u.filter((x) => x.key !== key));

  const start = (files: Iterable<File>) => {
    for (const file of files) {
      const key = ++seq.current;
      const problem = uploadProblem(file);
      const abort = new AbortController();
      setUploads((u) => [...u, { key, name: file.name, size: file.size, progress: 0, state: problem ? "error" : "uploading", error: problem ?? undefined, abort }]);
      if (problem) continue;
      api.copilot
        .upload(file, { tender, signal: abort.signal, onProgress: (progress) => patch(key, { progress }) })
        .then(() => {
          patch(key, { state: "done", progress: 1 });
          qc.invalidateQueries({ queryKey: ["copilot"] });
          qc.invalidateQueries({ queryKey: ["workspace"] });
          setTimeout(() => drop(key), 4000);
        })
        .catch((e) => {
          if (e instanceof DOMException && e.name === "AbortError") return drop(key);
          const quota = quotaExceeded(e);
          patch(key, { state: "error", error: quota?.message ?? errorMessage(e, "Upload failed"), quotaLimit: quota?.limit });
        });
    }
  };

  return (
    <div className={className}>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          start(Array.from(e.dataTransfer.files));
        }}
        className={cx(
          "flex flex-col items-center rounded-lg border border-dashed px-4 py-6 text-center transition-colors",
          over ? "border-signal bg-signal-soft" : "border-line-strong bg-surface hover:border-ink-3",
        )}
      >
        <UploadCloud className={cx("size-5", over ? "text-signal-text" : "text-ink-3")} aria-hidden="true" />
        <p className="mt-2 text-sm text-ink">
          Drop tender PDFs here or{" "}
          <button type="button" onClick={() => input.current?.click()} className="font-medium underline decoration-line-strong underline-offset-4 hover:decoration-signal">
            choose files
          </button>
        </p>
        <p className="mt-1 text-xs text-ink-3">NIT, BOQ, corrigenda · PDF up to 25 MB each · scanned pages are read with OCR</p>
        <input
          ref={input}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          className="sr-only"
          tabIndex={-1}
          aria-label="Choose PDF files"
          onChange={(e) => {
            if (e.target.files) start(Array.from(e.target.files));
            e.target.value = "";
          }}
        />
      </div>
      {uploads.length > 0 && (
        <ul className="mt-2 space-y-2" aria-live="polite">
          {uploads.map((u) => (
            <li key={u.key} className="rounded-md border border-line bg-surface px-3 py-2.5">
              <div className="flex items-center gap-2.5 text-sm">
                {u.state === "error" ? (
                  <CircleAlert className="size-4 shrink-0 text-critical" aria-hidden="true" />
                ) : (
                  <FileText className="size-4 shrink-0 text-ink-3" aria-hidden="true" />
                )}
                <span className="min-w-0 flex-1 truncate text-ink">{u.name}</span>
                <span className="num shrink-0 text-xs text-ink-3">
                  {u.state === "uploading" ? `${Math.round(u.progress * 100)}%` : u.state === "done" ? "Uploaded" : formatBytes(u.size)}
                </span>
                {u.state === "uploading" ? (
                  <button type="button" onClick={() => u.abort.abort()} className="text-ink-3 hover:text-ink" aria-label={`Cancel upload of ${u.name}`}>
                    <X className="size-4" />
                  </button>
                ) : u.state === "error" ? (
                  <button type="button" onClick={() => drop(u.key)} className="text-ink-3 hover:text-ink" aria-label={`Dismiss ${u.name}`}>
                    <X className="size-4" />
                  </button>
                ) : null}
              </div>
              {u.state === "uploading" && (
                <div
                  className="bar mt-2"
                  role="progressbar"
                  aria-label={`Uploading ${u.name}`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(u.progress * 100)}
                >
                  <span style={{ width: `${Math.max(2, u.progress * 100)}%` }} />
                </div>
              )}
              {u.state === "error" &&
                (u.quotaLimit !== undefined ? (
                  <UpgradeNotice limit={u.quotaLimit} message={u.error} className="mt-2" />
                ) : (
                  <p className="mt-1 text-xs text-critical">{u.error}</p>
                ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StatusTag({ d }: { d: CopilotDocument }) {
  if (d.status === "processing")
    return (
      <Tag>
        <Loader2 className="size-3 animate-spin" aria-hidden="true" /> Reading
      </Tag>
    );
  if (d.status === "failed") return <Tag tone="critical">Failed</Tag>;
  return <Tag tone="good">Ready</Tag>;
}

/** The workspace's documents. With `onToggle`, ready ones get a checkbox to narrow questions. */
export function DocumentList({
  docs,
  loading,
  selected,
  onToggle,
  showTender,
  empty = "No documents yet.",
}: {
  docs: CopilotDocument[] | undefined;
  loading?: boolean;
  selected?: Set<number>;
  onToggle?: (id: number) => void;
  showTender?: boolean;
  empty?: string;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [confirm, setConfirm] = useState<number | null>(null);
  const del = useMutation({
    mutationFn: api.copilot.deleteDocument,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["copilot"] });
      setConfirm(null);
      toast("success", "Document deleted");
    },
    onError: (e) => toast("error", errorMessage(e, "Couldn't delete the document")),
  });

  if (loading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    );
  }
  if (!docs?.length) return <p className="rounded-md border border-line px-3 py-3 text-sm text-ink-3">{empty}</p>;
  return (
    <ul className="divide-y divide-line rounded-md border border-line bg-surface">
      {docs.map((d) => (
        <li key={d.id} className="px-3 py-2.5">
          <div className="flex items-start gap-2.5">
            {onToggle ? (
              <input
                type="checkbox"
                className="mt-1 size-4 shrink-0 accent-[var(--signal)]"
                checked={selected?.has(d.id) ?? false}
                disabled={d.status !== "ready"}
                onChange={() => onToggle(d.id)}
                aria-label={`Use ${d.filename}`}
              />
            ) : (
              <FileText className="mt-0.5 size-4 shrink-0 text-ink-3" aria-hidden="true" />
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-ink" title={d.filename}>
                {d.filename}
              </p>
              <p className="num mt-0.5 text-[11px] text-ink-3">
                {d.status === "ready" ? `${d.pages} pages${d.ocr_pages ? ` · ${d.ocr_pages} OCR` : ""} · ${d.chunks} passages` : formatDate(d.created_at)}
              </p>
              {showTender && d.tender && (
                <Link to={`/tenders/${d.tender.id}`} className="num mt-1 block truncate text-[11px] text-ink-2 hover:text-ink" title={d.tender.title}>
                  {d.tender.source_tender_id}
                </Link>
              )}
              {d.status === "failed" && d.error && <p className="mt-1 text-xs text-critical">{d.error}</p>}
            </div>
            <StatusTag d={d} />
          </div>
          <div className="mt-1.5 flex justify-end">
            {confirm === d.id ? (
              <span className="inline-flex items-center gap-1.5 text-xs text-ink-2">
                Delete for everyone in the workspace?
                <Button size="sm" variant="danger" className="h-7" onClick={() => del.mutate(d.id)} disabled={del.isPending}>
                  Delete
                </Button>
                <Button size="sm" variant="ghost" className="h-7" onClick={() => setConfirm(null)}>
                  Keep
                </Button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setConfirm(d.id)}
                className="inline-flex items-center gap-1 text-[11px] text-ink-3 hover:text-critical"
                aria-label={`Delete ${d.filename}`}
              >
                <Trash2 className="size-3" aria-hidden="true" /> Delete
              </button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
