/** Links for subscribing to the pipeline's iCal feed (GET /api/pipeline/calendar.ics?token=…).
 *  Calendar apps poll the feed, so a subscription keeps deadlines current without us. */

/** webcal:// makes Apple Calendar and desktop Outlook offer to subscribe, not download. */
export function webcalUrl(feed: string): string {
  return feed.replace(/^https?:\/\//i, "webcal://");
}

/** Google Calendar's "add by URL", prefilled. Google refreshes subscribed feeds every few hours. */
export function googleCalendarUrl(feed: string): string {
  return `https://calendar.google.com/calendar/render?cid=${encodeURIComponent(webcalUrl(feed))}`;
}

/** Outlook on the web: Add calendar → Subscribe from web, prefilled. */
export function outlookUrl(feed: string, name = "TenderLens bids"): string {
  return `https://outlook.live.com/calendar/0/addfromweb?url=${encodeURIComponent(feed)}&name=${encodeURIComponent(name)}`;
}
