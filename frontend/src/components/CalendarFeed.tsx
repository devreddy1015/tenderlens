import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Check, Copy, RefreshCw, ShieldAlert } from "lucide-react";
import { useId, useState } from "react";
import { api, errorMessage, type Workspace } from "../lib/api";
import { googleCalendarUrl, outlookUrl, webcalUrl } from "../lib/calendar";
import { useWorkspace } from "../lib/queries";
import { useToast } from "../lib/toast";
import { Button, ButtonAnchor, cx, inputClass, Skeleton } from "./ui";

/** Subscribe to the pipeline's deadlines in Google Calendar, Outlook or Apple Calendar.
 *  The token in the URL is the only credential, so owners and admins can rotate it. */
export function CalendarFeed({ className }: { className?: string }) {
  const ws = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const id = useId();
  const [copied, setCopied] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const rotate = useMutation({
    mutationFn: api.workspace.rotateCalendar,
    onSuccess: ({ calendar_url }) => {
      qc.setQueryData<Workspace>(["workspace"], (w) => w && { ...w, calendar_url });
      setConfirm(false);
      toast("success", "New calendar link created. Re-subscribe with it; the old one no longer works.");
    },
    onError: (e) => toast("error", errorMessage(e, "Couldn't rotate the link")),
  });

  if (ws.isLoading) return <Skeleton className={cx("h-40 w-full", className)} />;
  const url = ws.data?.calendar_url;
  if (!url) return null;
  const canRotate = ws.data?.role === "owner" || ws.data?.role === "admin";
  const copy = () =>
    navigator.clipboard?.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });

  return (
    <div className={cx("space-y-4", className)}>
      <p className="text-sm text-ink-2">
        Bid due dates and bid openings of every tracked tender not yet submitted, as a calendar your whole team can subscribe to. Calendar apps refresh it on
        their own.
      </p>
      <div>
        <label htmlFor={`${id}-url`} className="mb-1.5 block text-sm font-medium text-ink">
          Calendar link
        </label>
        <div className="flex gap-2">
          <input id={`${id}-url`} readOnly value={url} onFocus={(e) => e.currentTarget.select()} className={cx(inputClass, "num min-w-0 flex-1 text-[13px]")} />
          <Button onClick={copy} aria-label="Copy calendar link">
            {copied ? <Check className="size-4 text-good" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}
            <span className="hidden sm:inline">{copied ? "Copied" : "Copy"}</span>
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <ButtonAnchor href={googleCalendarUrl(url)} size="sm" variant="primary">
          <CalendarPlus className="size-3.5" aria-hidden="true" /> Google Calendar
        </ButtonAnchor>
        <ButtonAnchor href={outlookUrl(url)} size="sm">
          Outlook.com
        </ButtonAnchor>
        <a href={webcalUrl(url)} className="btn btn-secondary btn-sm">
          Apple Calendar / Outlook desktop
        </a>
      </div>
      <details className="rounded-md border border-line px-3 py-2.5 text-sm text-ink-2">
        <summary className="cursor-pointer font-medium text-ink select-none">Add it by URL in Google Calendar</summary>
        <ol className="mt-2 list-decimal space-y-1 pl-5">
          <li>Copy the calendar link above.</li>
          <li>
            Open Google Calendar on the web, then <span className="text-ink">Other calendars → + → From URL</span>.
          </li>
          <li>
            Paste the link and press <span className="text-ink">Add calendar</span>. It appears on your phone too.
          </li>
        </ol>
        <p className="mt-2 text-xs text-ink-3">Google refreshes subscribed calendars every few hours, so a newly tracked tender can take a while to show.</p>
      </details>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-3">
        <p className="flex min-w-0 flex-1 items-start gap-1.5 text-xs text-ink-3">
          <ShieldAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          Anyone with this link sees your tracked tenders and their deadlines. Keep it inside the team.
        </p>
        {canRotate &&
          (confirm ? (
            <span className="inline-flex flex-wrap items-center gap-1.5 text-xs text-ink-2" role="group" aria-label="Confirm rotating the calendar link">
              Every calendar using the old link stops updating.
              <Button size="sm" variant="danger" className="h-7" onClick={() => rotate.mutate()} disabled={rotate.isPending}>
                {rotate.isPending ? "Rotating…" : "Rotate link"}
              </Button>
              <Button size="sm" variant="ghost" className="h-7" onClick={() => setConfirm(false)}>
                Keep
              </Button>
            </span>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}>
              <RefreshCw className="size-3.5" aria-hidden="true" /> Rotate link
            </Button>
          ))}
      </div>
    </div>
  );
}
