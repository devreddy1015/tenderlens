import { FileText } from "lucide-react";
import { cx } from "../ui";

/** "file.pdf p. 3": a toggle that reveals the quoted passage (see CitationQuote). */
export function CitationChip({
  n,
  filename,
  page,
  open,
  onToggle,
  controls,
}: {
  n?: number;
  filename: string;
  page: number | null;
  open: boolean;
  onToggle: () => void;
  controls?: string;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      aria-controls={controls}
      title={open ? "Hide the quote" : "Show the quote"}
      className={cx(
        "tag h-6 max-w-full gap-1 px-1.5 text-[11.5px] transition-colors",
        open ? "tag-signal" : "hover:border-line-strong hover:text-ink",
      )}
    >
      {n !== undefined ? <span className="num text-signal-text">[{n}]</span> : <FileText className="size-3 text-ink-3" aria-hidden="true" />}
      <span className="max-w-44 truncate">{filename}</span>
      {page !== null && <span className="num shrink-0 text-ink-3">p. {page}</span>}
    </button>
  );
}

export function CitationQuote({ id, quote, filename, page }: { id?: string; quote: string; filename: string; page: number | null }) {
  return (
    <blockquote id={id} className="border-l-2 border-signal bg-surface-2/60 py-2 pr-3 pl-3 text-sm">
      <p className="text-ink-2">“{quote.trim()}”</p>
      <footer className="num mt-1 text-[11px] text-ink-3">
        {filename}
        {page !== null && ` · page ${page}`}
      </footer>
    </blockquote>
  );
}
