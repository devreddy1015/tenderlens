import { useQuery } from "@tanstack/react-query";
import { FileText, Loader2, MessageCircleQuestion, ShieldCheck, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Button, Card, cx, inputClass } from "./ui";

/** Optional integration with DocIntel (served at /docintel/ by nginx). Hidden entirely when
 *  DocIntel isn't running or has no documents for this tender. */

interface Doc {
  id: number;
  filename: string;
  pages: number;
  chunks: number;
  ocr_used: boolean;
}

interface Citation {
  document: string;
  page: number;
  cited_text: string;
}

interface Final {
  status: string;
  answer: string;
  citations: Citation[];
  grounding: { unsupported: string[] } | null;
  error: string | null;
}

const SUGGESTIONS = ["How much bid security has to be paid?", "What experience must a bidder show?", "What penalty applies for late completion?"];

const STATUS: Record<string, { label: string; tone: "good" | "neutral" | "bad" }> = {
  answered: { label: "Answered from the documents", tone: "good" },
  abstained: { label: "Not in the documents", tone: "neutral" },
  no_context: { label: "Not in the documents", tone: "neutral" },
  rejected: { label: "Draft failed the fact check", tone: "bad" },
  refused: { label: "Declined", tone: "bad" },
  error: { label: "Something went wrong", tone: "bad" },
};

async function* sse(r: Response): AsyncGenerator<{ type: string; [k: string]: unknown }> {
  const reader = r.body!.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const data = buf.slice(0, i).split("\n").find((l) => l.startsWith("data: "));
      buf = buf.slice(i + 2);
      if (data) yield JSON.parse(data.slice(6));
    }
  }
}

export function AskDocuments({ tenderId }: { tenderId: string }) {
  const docs = useQuery({
    queryKey: ["docintel-docs", tenderId],
    queryFn: async () => {
      const r = await fetch(`/docintel/documents?tender_id=${encodeURIComponent(tenderId)}`);
      if (!r.ok) return [] as Doc[];
      return (await r.json()) as Doc[];
    },
    retry: false,
    staleTime: 5 * 60_000,
  });
  const [q, setQ] = useState("");
  const [draft, setDraft] = useState("");
  const [final, setFinal] = useState<Final | null>(null);
  const [busy, setBusy] = useState(false);

  if (!docs.data?.length) return null;

  const ask = async (question: string) => {
    setBusy(true);
    setDraft("");
    setFinal(null);
    try {
      const r = await fetch("/docintel/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, tender_id: tenderId }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        setFinal({ status: "error", answer: body.detail ?? r.statusText, citations: [], grounding: null, error: null });
        return;
      }
      for await (const ev of sse(r)) {
        if (ev.type === "delta") setDraft((d) => d + (ev.text as string));
        else if (ev.type === "final") setFinal(ev as unknown as Final);
      }
    } catch {
      setFinal({ status: "error", answer: "Couldn't reach the document service.", citations: [], grounding: null, error: null });
    } finally {
      setBusy(false);
    }
  };

  const st = final ? (STATUS[final.status] ?? STATUS.error) : null;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
        <h2 className="label flex items-center gap-2">
          <MessageCircleQuestion className="size-3.5 text-signal-text" aria-hidden="true" /> Ask the documents
        </h2>
        <span className="num text-xs text-ink-3">
          {docs.data.length} {docs.data.length === 1 ? "document" : "documents"} · {docs.data.reduce((n, d) => n + d.pages, 0)} pages
        </span>
      </div>
      <div className="p-5">
        <p className="text-sm text-ink-2">
          Answers come only from {docs.data.length === 1 ? "the document" : "these documents"}, with the page they came from. Every number is checked against the cited text.
        </p>
        <ul className="mt-3 flex flex-wrap gap-1.5">
          {docs.data.map((d) => (
            <li key={d.id} className="tag">
              <FileText className="size-3.5 text-ink-3" aria-hidden="true" />
              <span className="max-w-56 truncate">{d.filename}</span>
              <span className="num text-ink-3">
                {d.pages}p{d.ocr_used ? " · OCR" : ""}
              </span>
            </li>
          ))}
        </ul>
        <form
          className="mt-5 flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            if (q.trim().length >= 3) ask(q.trim());
          }}
        >
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. What turnover is required?" className={inputClass} aria-label="Question about the documents" maxLength={500} />
          <Button type="submit" variant="primary" disabled={busy || q.trim().length < 3} className="shrink-0">
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null} Ask
          </Button>
        </form>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" onClick={() => (setQ(s), ask(s))} className="tag hover:border-line-strong hover:text-ink">
              {s}
            </button>
          ))}
        </div>

        {(draft || final) && (
          <div className="mt-5 rounded-md border border-line bg-surface-2/50 p-4" aria-live="polite">
            {st && (
              <span className={cx("tag mb-3", st.tone === "good" && "tag-good", st.tone === "bad" && "tag-critical")}>
                {st.tone === "good" ? <ShieldCheck className="size-3.5" aria-hidden="true" /> : <TriangleAlert className="size-3.5" aria-hidden="true" />}
                {st.label}
              </span>
            )}
            {/* Until the fact check finishes, the streamed text is only a draft. */}
            <p className={cx("text-[15px] leading-relaxed", final ? "text-ink" : "text-ink-3")}>{final ? final.answer : draft}</p>
            {final?.citations.length ? (
              <ul className="mt-4 space-y-3">
                {final.citations.slice(0, 4).map((c, i) => (
                  <li key={i} className="border-l-2 border-signal pl-3 text-sm">
                    <span className="num text-xs text-ink-3">
                      {c.document} · p. {c.page}
                    </span>
                    <span className="mt-0.5 block text-ink-2">“{c.cited_text.trim()}”</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {final?.status === "rejected" && final.grounding?.unsupported.length ? (
              <p className="mt-3 text-xs text-ink-3">Not found in the cited passages: {final.grounding.unsupported.join(", ")}</p>
            ) : null}
          </div>
        )}
      </div>
    </Card>
  );
}
