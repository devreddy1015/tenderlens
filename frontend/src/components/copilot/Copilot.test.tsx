import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CopilotDocument } from "../../lib/api";
import { mockFetch, renderPage, reply, SIGNED_IN } from "../../test/render";
import { BriefPanel, EligibilityPanel } from "./Brief";
import { DocumentList, UploadDropzone } from "./Documents";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const base = { "GET /api/auth/me": SIGNED_IN, "GET /api/config": {} };

/** XMLHttpRequest that answers every upload with `status` and `body`. */
function stubUpload(status: number, body: unknown) {
  const sent: FormData[] = [];
  class FakeXhr {
    status = 0;
    responseText = "";
    upload: { onprogress?: unknown } = {};
    onload?: () => void;
    onerror?: () => void;
    onabort?: () => void;
    open() {}
    setRequestHeader() {}
    abort() {}
    send(form: FormData) {
      sent.push(form);
      setTimeout(() => {
        this.status = status;
        this.responseText = JSON.stringify(body);
        this.onload?.();
      }, 0);
    }
  }
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  return sent;
}

const pdf = () => new File(["%PDF-1.7 tender"], "NIT.pdf", { type: "application/pdf" });

describe("Copilot uploads", () => {
  it("shows the server's {file: message} validation error", async () => {
    mockFetch(base);
    const sent = stubUpload(400, { file: "This PDF is encrypted; upload an unlocked copy." });
    renderPage(<UploadDropzone tender={42} />);

    fireEvent.change(screen.getByLabelText("Choose PDF files"), { target: { files: [pdf()] } });
    expect(await screen.findByText("This PDF is encrypted; upload an unlocked copy.")).toBeTruthy();
    expect(sent[0].get("tender")).toBe("42");
  });

  it("rejects a non-PDF before uploading it", async () => {
    mockFetch(base);
    const sent = stubUpload(201, {});
    renderPage(<UploadDropzone />);
    fireEvent.change(screen.getByLabelText("Choose PDF files"), { target: { files: [new File(["x"], "boq.xlsx", { type: "application/vnd.ms-excel" })] } });
    expect(await screen.findByText(/boq.xlsx is not a PDF/)).toBeTruthy();
    expect(sent).toHaveLength(0);
  });

  it("shows the upgrade prompt inline when the monthly document limit is reached", async () => {
    mockFetch(base);
    stubUpload(402, { detail: "Your plan's limit for documents_per_month is reached.", code: "quota_exceeded", limit: "documents_per_month" });
    renderPage(<UploadDropzone />);
    fireEvent.change(screen.getByLabelText("Choose PDF files"), { target: { files: [pdf()] } });
    expect(await screen.findByText("You've reached your plan's limit for document uploads.")).toBeTruthy();
  });
});

describe("Copilot processing status", () => {
  const doc = (over: Partial<CopilotDocument>): CopilotDocument => ({
    id: 1,
    filename: "NIT.pdf",
    pages: 0,
    chunks: 0,
    status: "processing",
    error: "",
    ocr_pages: 0,
    tender: null,
    created_at: "2026-10-06T05:00:00Z",
    ...over,
  });

  it("says a document is still being read, and why one failed", async () => {
    mockFetch(base);
    renderPage(<DocumentList docs={[doc({}), doc({ id: 2, filename: "BOQ.pdf", status: "failed", error: "No text could be read from this PDF." })]} />);
    expect((await screen.findAllByText(/Reading 1 document/)).length).toBeGreaterThan(0);
    expect(screen.getByText("No text could be read from this PDF.")).toBeTruthy();
  });

  it("shows the brief as 'being read' on 400 {detail, status: processing}", async () => {
    mockFetch({ ...base, "GET /api/copilot/documents/1/brief": reply(400, { detail: "This document is still being processed.", status: "processing" }) });
    renderPage(<BriefPanel scope={{ document: 1 }} />);
    expect(await screen.findByText(/still being read/)).toBeTruthy();
  });

  it("shows the server's message when the document failed", async () => {
    mockFetch({ ...base, "GET /api/copilot/eligibility": reply(400, { detail: "Processing failed: no text found.", status: "failed" }) });
    renderPage(<EligibilityPanel scope={{ document: 1 }} />);
    expect(await screen.findByText("Processing failed: no text found.")).toBeTruthy();
  });

  it("explains a tender brief with no ready documents yet", async () => {
    mockFetch({ ...base, "GET /api/copilot/brief": { fields: [], missing: [], generated_at: "2026-10-06T05:00:00Z", documents: 0 } });
    const { container } = renderPage(<BriefPanel scope={{ tender: 42 }} />);
    await screen.findByText(/0 documents/);
    expect(container.textContent).toMatch(/upload/i);
  });
});
