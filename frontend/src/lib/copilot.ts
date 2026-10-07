import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { type AnswerStatus, ApiError, type AskEvent, type AskFinal, api, type CopilotDocument, type Passage } from "./api";
import { useSignedIn } from "./queries";

/** Documents of the workspace (or of one tender), polled while any is still being read. */
export function useDocuments(tender?: number) {
  const signedIn = useSignedIn();
  return useQuery({
    queryKey: ["copilot", "documents", tender ?? "all"],
    queryFn: () => api.copilot.documents(tender),
    enabled: signedIn,
    refetchInterval: (q) => (q.state.data?.some((d: CopilotDocument) => d.status === "processing") ? 3000 : false),
  });
}

/** When another document finishes reading, the brief and eligibility of its scope are stale:
 *  refetch them so the panels fill in without a reload. */
export function useRefreshWhenReady(readyCount: number) {
  const qc = useQueryClient();
  const last = useRef(readyCount);
  useEffect(() => {
    if (readyCount === last.current) return;
    last.current = readyCount;
    qc.invalidateQueries({ queryKey: ["copilot", "brief"] });
    qc.invalidateQueries({ queryKey: ["copilot", "eligibility"] });
  }, [readyCount, qc]);
}

/** A brief or eligibility request on a document that isn't ready answers 400
 *  {detail, status}; this returns that status ("processing" | "failed"), else null. */
export function notReady(e: unknown): "processing" | "failed" | null {
  if (!(e instanceof ApiError) || e.status !== 400) return null;
  const st = e.body.status;
  const v = Array.isArray(st) ? st[0] : st;
  return v === "processing" || v === "failed" ? v : null;
}

export function useCopilotStatus() {
  const signedIn = useSignedIn();
  return useQuery({ queryKey: ["copilot", "status"], queryFn: api.copilot.status, enabled: signedIn, staleTime: 60_000, retry: false });
}

export const ANSWER_STATUS: Record<AnswerStatus, { label: string; tone: "good" | "neutral" | "critical"; hint: string }> = {
  answered: {
    label: "Answered from the documents",
    tone: "good",
    hint: "Every number and date in this answer was found in the passage it cites.",
  },
  abstained: {
    label: "Not in the documents",
    tone: "neutral",
    hint: "The documents don't say. Check the corrigenda, or raise it at the pre-bid meeting.",
  },
  rejected: {
    label: "Withheld: failed the fact check",
    tone: "critical",
    hint: "The draft stated something the cited passages don't support, so it isn't shown as an answer.",
  },
  no_context: {
    label: "Nothing relevant found",
    tone: "neutral",
    hint: "No passage matches the question. Upload the tender's documents, or ask it another way.",
  },
  error: { label: "Something went wrong", tone: "critical", hint: "Try again in a moment." },
};

export const EXTRACTIVE_HINT =
  "The language model is offline, so this answer quotes the best-matching sentences from the documents word for word.";

/** One question and everything streamed back for it. */
export interface Turn {
  id: number;
  question: string;
  passages: Passage[];
  /** Streamed text: only a draft until the fact check sends the final answer. */
  draft: string;
  final: AskFinal | null;
  error: { message: string; quotaLimit?: string } | null;
  pending: boolean;
}

export function newTurn(id: number, question: string): Turn {
  return { id, question, passages: [], draft: "", final: null, error: null, pending: true };
}

/** Fold one stream event into a turn. Unknown event types are ignored, so the server can
 *  add new ones without breaking older clients. */
export function applyAskEvent(t: Turn, e: AskEvent): Turn {
  switch (e.type) {
    case "retrieval":
      return { ...t, passages: e.passages ?? [] };
    case "delta":
      return { ...t, draft: t.draft + (e.text ?? "") };
    case "final":
      return { ...t, final: { ...e, citations: e.citations ?? [] }, pending: false };
    default:
      return t;
  }
}

/** Splits "EMD is ₹2 lakh [1]." into text and citation markers, keeping only markers that
 *  point at a real citation. */
export function splitCitations(text: string, known: Set<number>): (string | number)[] {
  const out: (string | number)[] = [];
  let last = 0;
  for (const m of text.matchAll(/\[(\d+)\]/g)) {
    const n = Number(m[1]);
    if (!known.has(n)) continue;
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(n);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export const SUGGESTED_QUESTIONS = [
  "How much EMD has to be paid, and in what form?",
  "What turnover and experience must a bidder show?",
  "What penalty applies for late completion?",
  "Which documents must be uploaded with the bid?",
];
