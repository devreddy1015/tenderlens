import { useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Loader2, ShieldCheck, Square, TriangleAlert, Quote } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { api, errorMessage, quotaExceeded } from "../../lib/api";
import { ANSWER_STATUS, applyAskEvent, EXTRACTIVE_HINT, newTurn, splitCitations, SUGGESTED_QUESTIONS, type Turn } from "../../lib/copilot";
import { UpgradeNotice } from "../Upgrade";
import { Button, cx, inputBase, Skeleton, Tag } from "../ui";
import { CitationChip, CitationQuote } from "./Citation";

function TurnView({ t }: { t: Turn }) {
  const [open, setOpen] = useState<number | null>(null);
  const base = useId();
  const f = t.final;
  const st = f ? (ANSWER_STATUS[f.status] ?? ANSWER_STATUS.error) : null;
  const known = new Set(f?.citations.map((c) => c.n));
  const text = f ? f.answer : t.draft;
  const cited = f?.citations.find((c) => c.n === open);
  const toggle = (n: number) => setOpen(open === n ? null : n);

  return (
    <li>
      <p className="flex gap-2.5 text-[15px] font-medium text-ink">
        <span className="label pt-1 text-signal-text">Q</span>
        <span className="min-w-0">{t.question}</span>
      </p>
      <div className="mt-2.5 rounded-md border border-line bg-surface p-4">
        <div className="mb-2.5 flex flex-wrap items-center gap-1.5">
          {st ? (
            <Tag tone={st.tone === "good" ? "good" : st.tone === "critical" ? "critical" : undefined}>
              {st.tone === "good" ? <ShieldCheck className="size-3.5" aria-hidden="true" /> : <TriangleAlert className="size-3.5" aria-hidden="true" />}
              {st.label}
            </Tag>
          ) : t.pending ? (
            <span className="label flex items-center gap-2">
              <Loader2 className="size-3.5 animate-spin text-signal-text" aria-hidden="true" />
              {t.draft ? "Drafting, then fact-checking" : t.passages.length ? `Read ${t.passages.length} passages` : "Searching the documents"}
            </span>
          ) : null}
          {f?.mode === "extractive" && (
            <Tag tone="signal">
              <Quote className="size-3.5" aria-hidden="true" /> Extractive · model offline
            </Tag>
          )}
        </div>

        {text ? (
          <p
            className={cx(
              "text-[15px] leading-relaxed whitespace-pre-line",
              !f ? "text-ink-3" : f.status === "answered" ? "text-ink" : "text-ink-2",
            )}
          >
            {splitCitations(text, known).map((part, i) =>
              typeof part === "string" ? (
                part
              ) : (
                <button
                  key={i}
                  type="button"
                  onClick={() => toggle(part)}
                  aria-expanded={open === part}
                  aria-controls={`${base}-quote`}
                  aria-label={`Source ${part}`}
                  className={cx("num mx-0.5 rounded px-0.5 align-super text-[10px] font-medium", open === part ? "bg-signal text-signal-ink" : "text-signal-text hover:bg-signal-soft")}
                >
                  [{part}]
                </button>
              ),
            )}
            {!f && t.pending && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-ink-3 align-text-bottom" aria-hidden="true" />}
          </p>
        ) : t.pending ? (
          <div className="space-y-2" aria-hidden="true">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ) : null}

        {st && f?.status !== "answered" && <p className="mt-2 text-xs text-ink-3">{st.hint}</p>}
        {f?.mode === "extractive" && <p className="mt-2 text-xs text-ink-3">{EXTRACTIVE_HINT}</p>}
        {f?.status === "rejected" && (f.grounding?.unsupported.length ?? 0) > 0 && (
          <p className="mt-2 text-xs text-ink-3">
            Not found in the cited passages: <span className="num text-ink-2">{f.grounding!.unsupported.join(", ")}</span>
          </p>
        )}

        {f && f.citations.length > 0 && (
          <div className="mt-3.5 border-t border-line pt-3">
            <p className="label mb-2">Sources</p>
            <div className="flex flex-wrap gap-1.5">
              {f.citations.map((c) => (
                <CitationChip key={c.n} n={c.n} filename={c.filename} page={c.page} open={open === c.n} onToggle={() => toggle(c.n)} controls={`${base}-quote`} />
              ))}
            </div>
            {cited && (
              <div className="mt-2.5">
                <CitationQuote id={`${base}-quote`} quote={cited.quote} filename={cited.filename} page={cited.page} />
              </div>
            )}
          </div>
        )}

        {!f && t.passages.length > 0 && (
          <details className="mt-3 text-xs text-ink-3">
            <summary className="cursor-pointer select-none hover:text-ink">Passages being read</summary>
            <ul className="mt-2 space-y-1">
              {t.passages.map((p) => (
                <li key={p.n} className="num truncate">
                  [{p.n}] {p.filename} p. {p.page}
                </li>
              ))}
            </ul>
          </details>
        )}

        {t.error &&
          (t.error.quotaLimit !== undefined ? (
            <UpgradeNotice limit={t.error.quotaLimit} message={t.error.message} className="mt-2" />
          ) : (
            <p className="mt-2 text-sm text-critical">{t.error.message}</p>
          ))}

        {f && (
          <p className="num mt-3 text-[11px] text-ink-3">
            {[f.model, f.latency_ms ? `${(f.latency_ms / 1000).toLocaleString("en-IN", { maximumFractionDigits: 1 })} s` : null].filter(Boolean).join(" · ")}
          </p>
        )}
      </div>
    </li>
  );
}

/** Questions answered only from the uploaded documents, streamed as they're written, then
 *  fact-checked: numbers and dates must appear in the passage they cite. */
export function AskPanel({ tender, documentIds, ready, emptyHint }: { tender?: number; documentIds?: number[]; ready: boolean; emptyHint?: string }) {
  const qc = useQueryClient();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const abort = useRef<AbortController | null>(null);
  const seq = useRef(0);
  const end = useRef<HTMLDivElement>(null);
  const busy = turns.some((t) => t.pending);

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (turns.length) end.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [turns.length]);

  const update = (id: number, fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)));

  const ask = async (question: string) => {
    const id = ++seq.current;
    setTurns((ts) => [...ts, newTurn(id, question)]);
    setQ("");
    const ctrl = new AbortController();
    abort.current = ctrl;
    try {
      const req = { question, ...(tender ? { tender } : {}), ...(documentIds?.length ? { document_ids: documentIds } : {}) };
      for await (const ev of api.copilot.ask(req, ctrl.signal)) update(id, (t) => applyAskEvent(t, ev));
      update(id, (t) => (t.pending ? { ...t, pending: false, error: { message: "The answer stopped before it finished. Try again." } } : t));
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        update(id, (t) => ({ ...t, pending: false, error: { message: "Stopped." } }));
        return;
      }
      const quota = quotaExceeded(e);
      update(id, (t) => ({ ...t, pending: false, error: { message: quota?.message ?? errorMessage(e), quotaLimit: quota?.limit } }));
    } finally {
      if (abort.current === ctrl) abort.current = null;
      qc.invalidateQueries({ queryKey: ["workspace"] });
    }
  };

  const submit = () => {
    const question = q.trim();
    if (question.length >= 3 && !busy && ready) ask(question);
  };

  return (
    <div>
      {turns.length === 0 ? (
        <div>
          <p className="text-sm text-ink-2">
            {ready
              ? "Ask anything about these documents. Every answer cites the page it came from; if the documents don't say, you'll be told so."
              : (emptyHint ?? "Upload the tender's documents first.")}
          </p>
          {ready && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {SUGGESTED_QUESTIONS.map((s) => (
                <button key={s} type="button" onClick={() => ask(s)} disabled={busy} className="tag h-auto min-h-7 py-1 text-left whitespace-normal hover:border-line-strong hover:text-ink">
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <ol className="space-y-6" aria-live="polite" aria-busy={busy}>
          {turns.map((t) => (
            <TurnView key={t.id} t={t} />
          ))}
        </ol>
      )}
      <div ref={end} />
      <form
        className="mt-5 flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={2}
          maxLength={500}
          disabled={!ready}
          placeholder={ready ? "e.g. What is the bid validity period?" : "Upload documents to ask questions"}
          aria-label="Question about the documents"
          className={cx(inputBase, "min-h-11 w-full flex-1 resize-y py-2.5 disabled:opacity-60")}
        />
        {busy ? (
          <Button type="button" onClick={() => abort.current?.abort()} className="h-11 shrink-0" aria-label="Stop answering">
            <Square className="size-3.5" aria-hidden="true" /> Stop
          </Button>
        ) : (
          <Button type="submit" variant="primary" disabled={!ready || q.trim().length < 3} className="h-11 shrink-0">
            Ask <ArrowUp className="size-4" aria-hidden="true" />
          </Button>
        )}
      </form>
      <p className="mt-1.5 text-[11px] text-ink-3">Enter to send · Shift+Enter for a new line · answers come from your documents only</p>
    </div>
  );
}
