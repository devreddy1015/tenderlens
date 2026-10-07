import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { googleCalendarUrl, webcalUrl } from "../lib/calendar";
import { workspace } from "../test/fixtures";
import { mockFetch, renderPage, SIGNED_IN } from "../test/render";
import { CalendarFeed } from "./CalendarFeed";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const FEED = "https://tenderlens.in/api/pipeline/calendar.ics?token=abc123";
const NEW_FEED = "https://tenderlens.in/api/pipeline/calendar.ics?token=xyz789";

describe("calendar links", () => {
  it("turns the feed into webcal and Google Calendar subscribe links", () => {
    expect(webcalUrl(FEED)).toBe("webcal://tenderlens.in/api/pipeline/calendar.ics?token=abc123");
    expect(webcalUrl("http://localhost:8080/x.ics")).toBe("webcal://localhost:8080/x.ics");
    expect(googleCalendarUrl(FEED)).toBe(`https://calendar.google.com/calendar/render?cid=${encodeURIComponent(webcalUrl(FEED))}`);
  });
});

describe("CalendarFeed", () => {
  it("shows the feed, copies it and links to the calendar apps", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    mockFetch({ "GET /api/auth/me": SIGNED_IN, "GET /api/config": {}, "GET /api/workspace": workspace() });
    renderPage(<CalendarFeed />);

    const input = (await screen.findByLabelText("Calendar link")) as HTMLInputElement;
    expect(input.value).toBe(FEED);
    expect(screen.getByRole("link", { name: /Google Calendar/ }).getAttribute("href")).toBe(googleCalendarUrl(FEED));
    expect(screen.getByRole("link", { name: /Apple Calendar/ }).getAttribute("href")).toBe(webcalUrl(FEED));

    fireEvent.click(screen.getByRole("button", { name: "Copy calendar link" }));
    expect(writeText).toHaveBeenCalledWith(FEED);
  });

  it("lets an owner rotate the link, only after confirming", async () => {
    const calls = mockFetch({
      "GET /api/auth/me": SIGNED_IN,
      "GET /api/config": {},
      "GET /api/workspace": workspace(),
      "POST /api/workspace/calendar-token": { calendar_url: NEW_FEED },
    });
    renderPage(<CalendarFeed />);

    fireEvent.click(await screen.findByRole("button", { name: /Rotate link/ }));
    const group = screen.getByRole("group", { name: "Confirm rotating the calendar link" });
    expect(group.textContent).toMatch(/stops updating/);
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Rotate link" }));
    await waitFor(() => expect((screen.getByLabelText("Calendar link") as HTMLInputElement).value).toBe(NEW_FEED));
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual(["/api/workspace/calendar-token"]);
  });

  it("doesn't offer rotation to members", async () => {
    mockFetch({ "GET /api/auth/me": SIGNED_IN, "GET /api/config": {}, "GET /api/workspace": workspace({ role: "member" }) });
    renderPage(<CalendarFeed />);
    await screen.findByLabelText("Calendar link");
    expect(screen.queryByRole("button", { name: /Rotate link/ })).toBeNull();
  });
});
