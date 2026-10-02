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
    <Card className="p-5 sm:p-6">
      <h2 className="flex items-center gap-2 font-semibold text-ink">
        <MessageCircleQuestion className="size-5 text-brand" /> Ask this tender's documents
      </h2>
      <p className="mt-1 text-sm text-ink-2">
        Answers come only from {docs.data.length === 1 ? "the document" : `${docs.data.length} documents`} below, with the page they came from. Every number is checked against the cited text.
      </p>
      <ul className="mt-3 flex flex-wrap gap-2 text-xs text-ink-3">
        {docs.data.map((d) => (
          <li key={d.id} className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1">
            <FileText className="size-3.5" /> {d.filename} · {d.pages} pages{d.ocr_used ? " · OCR" : ""}
          </li>
        ))}
      </ul>
      <form
        className="mt-4 flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (q.trim().length >= 3) ask(q.trim());
        }}
      >
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. What turnover is required?" className={inputClass} aria-label="Question about the documents" maxLength={500} />
        <Button type="submit" variant="primary" disabled={busy || q.trim().length < 3} className="h-11 shrink-0">
          {busy ? <Loader2 className="size-4 animate-spin" /> : null} Ask
        </Button>
      </form>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {SUGGESTIONS.map((s) => (
          <button key={s} type="button" onClick={() => (setQ(s), ask(s))} className="rounded-full border border-line px-2.5 py-1 text-xs text-ink-2 hover:border-brand hover:text-brand">
            {s}
          </button>
        ))}
      </div>

      {(draft || final) && (
        <div className="mt-5 rounded-xl border border-line bg-surface-2/50 p-4" aria-live="polite">
          {st && (
            <span
              className={cx(
                "mb-2 inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold",
                st.tone === "good" && "bg-good/10 text-good",
                st.tone === "neutral" && "bg-surface-2 text-ink-2",
                st.tone === "bad" && "bg-critical/10 text-critical",
              )}
            >
              {st.tone === "good" ? <ShieldCheck className="size-3.5" /> : <TriangleAlert className="size-3.5" />}
              {st.label}
            </span>
          )}
          {/* Until the fact check finishes, the streamed text is only a draft. */}
          <p className={cx("text-[15px] leading-relaxed", final ? "text-ink" : "text-ink-3")}>{final ? final.answer : draft}</p>
          {final?.citations.length ? (
            <ul className="mt-3 space-y-2">
              {final.citations.slice(0, 4).map((c, i) => (
                <li key={i} className="border-l-2 border-brand/40 pl-3 text-sm">
                  <span className="font-medium text-brand">
                    {c.document}, p. {c.page}
                  </span>
                  <span className="block text-ink-2">“{c.cited_text.trim()}”</span>
                </li>
              ))}
            </ul>
          ) : null}
          {final?.status === "rejected" && final.grounding?.unsupported.length ? (
            <p className="mt-2 text-xs text-ink-3">Not found in the cited passages: {final.grounding.unsupported.join(", ")}</p>
          ) : null}
        </div>
      )}
    </Card>
  );
}
