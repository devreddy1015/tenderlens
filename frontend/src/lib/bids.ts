import type { BidStatus } from "./api";

/** The bid pipeline's columns, in the order a bid moves through them. */
export const BID_STATUS: Record<BidStatus, { label: string; hint: string; tone?: "signal" | "good" | "critical" }> = {
  watching: { label: "Watching", hint: "Worth a look" },
  preparing: { label: "Preparing", hint: "Documents and pricing", tone: "signal" },
  submitted: { label: "Submitted", hint: "Bid is in", tone: "signal" },
  won: { label: "Won", hint: "Awarded to us", tone: "good" },
  lost: { label: "Lost", hint: "Awarded elsewhere", tone: "critical" },
  dropped: { label: "Dropped", hint: "Decided not to bid" },
};

/** Statuses that still need work before the deadline. */
export const ACTIVE_STATUSES: BidStatus[] = ["watching", "preparing"];
