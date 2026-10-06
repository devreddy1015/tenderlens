import { BookmarkCheck, BookmarkPlus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { BID_STATUSES, type BidStatus, type Tender } from "../lib/api";
import { BID_STATUS } from "../lib/bids";
import { useSignedIn, useTrack, useTracked, useUpdateTrack } from "../lib/queries";
import { SignInDialog } from "./SignIn";
import { Button, ButtonLink, cx, inputClass } from "./ui";

/** A small "Track" control for tender cards and rows; hidden for signed-out visitors. Sits
 *  above the card's full-size link (relative z-10) so it stays clickable. */
export function TrackChip({ tender, className }: { tender: Tender; className?: string }) {
  const signedIn = useSignedIn();
  const tracked = useTracked(tender.id);
  const track = useTrack();
  if (!signedIn) return null;
  if (tracked) {
    return (
      <Link
        to="/pipeline"
        className={cx("tag tag-signal relative z-10 h-6 px-1.5 text-[11.5px]", className)}
        title="In your bid pipeline"
        aria-label={`In pipeline: ${BID_STATUS[tracked.status].label}`}
      >
        <BookmarkCheck className="size-3.5" aria-hidden="true" />
        {BID_STATUS[tracked.status].label}
      </Link>
    );
  }
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        track.mutate({ tender: tender.id });
      }}
      disabled={track.isPending}
      className={cx("tag relative z-10 h-6 px-1.5 text-[11.5px] transition-colors hover:border-line-strong hover:text-ink disabled:opacity-60", className)}
      title="Track in your bid pipeline"
      aria-label={`Track “${tender.title}” in your pipeline`}
    >
      <BookmarkPlus className="size-3.5" aria-hidden="true" />
      Track
    </button>
  );
}

/** "Track in pipeline" on a tender's page; once tracked, the bid's status, changeable here. */
export function TrackPanel({ tender }: { tender: Tender }) {
  const signedIn = useSignedIn();
  const tracked = useTracked(tender.id);
  const track = useTrack();
  const update = useUpdateTrack();
  const [signIn, setSignIn] = useState(false);

  if (tracked) {
    return (
      <div className="rounded-md border border-signal/40 bg-signal-soft/60 p-3">
        <p className="label flex items-center gap-1.5 text-signal-text">
          <BookmarkCheck className="size-3.5" aria-hidden="true" /> In your pipeline
        </p>
        <div className="mt-2 flex items-center gap-2">
          <select
            value={tracked.status}
            onChange={(e) => update.mutate({ id: tracked.id, patch: { status: e.target.value as BidStatus } })}
            className={cx(inputClass, "h-9 flex-1")}
            aria-label="Bid status"
          >
            {BID_STATUSES.map((s) => (
              <option key={s} value={s}>
                {BID_STATUS[s].label}
              </option>
            ))}
          </select>
          <ButtonLink to="/pipeline" size="sm" className="h-9">
            Board
          </ButtonLink>
        </div>
      </div>
    );
  }
  return (
    <>
      <Button className="w-full" onClick={() => (signedIn ? track.mutate({ tender: tender.id }) : setSignIn(true))} disabled={track.isPending}>
        <BookmarkPlus className="size-4" aria-hidden="true" /> {track.isPending ? "Adding…" : "Track in pipeline"}
      </Button>
      <SignInDialog open={signIn} onClose={() => setSignIn(false)} title="Sign in to track this tender" onDone={() => track.mutate({ tender: tender.id })}>
        Your bid pipeline keeps every tender you're working on in one board, with deadlines, notes and your team.
      </SignInDialog>
    </>
  );
}
