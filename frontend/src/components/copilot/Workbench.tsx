import { ClipboardList, MessageCircleQuestion, Scale } from "lucide-react";
import { useState } from "react";
import type { DocScope } from "../../lib/api";
import { EXTRACTIVE_HINT, useCopilotStatus } from "../../lib/copilot";
import { cx, Segmented } from "../ui";
import { AskPanel } from "./Ask";
import { BriefPanel, EligibilityPanel } from "./Brief";

/** Whether answers are written by the model or quoted (model offline). */
export function ModelStatus({ className }: { className?: string }) {
  const s = useCopilotStatus();
  if (!s.data) return null;
  const on = s.data.llm.available;
  return (
    <span className={cx("num inline-flex items-center gap-1.5 text-xs text-ink-3", className)} title={on ? "Answers are written by our own model, then fact-checked" : EXTRACTIVE_HINT}>
      <span className={cx("size-1.5 rounded-full", on ? "bg-good" : "bg-signal")} aria-hidden="true" />
      {on ? s.data.llm.model || "Model online" : "Model offline · quoting answers"}
    </span>
  );
}

export type CopilotTab = "brief" | "ask" | "eligibility";

/** Brief, Ask and Eligibility over one scope. `scope` is null when there is nothing to brief
 *  yet (no tender and not exactly one document); Ask still works over `documentIds`. */
export function Workbench({
  scope,
  tender,
  documentIds,
  ready,
  initial = "brief",
  scopeHint,
}: {
  scope: DocScope | null;
  tender?: number;
  documentIds?: number[];
  ready: boolean;
  initial?: CopilotTab;
  scopeHint?: string;
}) {
  const [tab, setTab] = useState<CopilotTab>(initial);
  const hint = <p className="rounded-md border border-line px-3 py-3 text-sm text-ink-2">{scopeHint ?? "Upload the tender's documents first."}</p>;
  return (
    <div>
      <Segmented<CopilotTab>
        label="Copilot view"
        value={tab}
        onChange={setTab}
        className="mb-5"
        options={[
          { value: "brief", label: (<><ClipboardList className="size-3.5" aria-hidden="true" /> Bid brief</>) },
          { value: "ask", label: (<><MessageCircleQuestion className="size-3.5" aria-hidden="true" /> Ask</>) },
          { value: "eligibility", label: (<><Scale className="size-3.5" aria-hidden="true" /> Eligibility</>) },
        ]}
      />
      {tab === "ask" ? (
        <AskPanel tender={tender} documentIds={documentIds} ready={ready} emptyHint={scopeHint} />
      ) : !ready || !scope ? (
        hint
      ) : tab === "brief" ? (
        <BriefPanel scope={scope} />
      ) : (
        <EligibilityPanel scope={scope} />
      )}
    </div>
  );
}
