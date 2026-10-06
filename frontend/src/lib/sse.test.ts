// @vitest-environment node
import { describe, expect, it } from "vitest";
import { createSSEParser, type SSEMessage, sseJson } from "./sse";

function parse(chunks: string[]): SSEMessage[] {
  const out: SSEMessage[] = [];
  const p = createSSEParser((m) => out.push(m));
  for (const c of chunks) p.push(c);
  p.end();
  return out;
}

function stream(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const x of chunks) c.enqueue(typeof x === "string" ? enc.encode(x) : x);
      c.close();
    },
  });
}

async function collect<T>(it: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const x of it) out.push(x);
  return out;
}

describe("createSSEParser", () => {
  it("parses whole events", () => {
    expect(parse(['data: {"a":1}\n\ndata: {"a":2}\n\n']).map((m) => m.data)).toEqual(['{"a":1}', '{"a":2}']);
  });

  it("survives every possible chunk boundary", () => {
    const text = 'data: {"type":"delta","text":"EMD ₹2 lakh"}\r\n\r\nevent: done\ndata: {"type":"final"}\n\n';
    const want = parse([text]);
    expect(want).toHaveLength(2);
    for (let i = 1; i < text.length; i++) {
      expect(parse([text.slice(0, i), text.slice(i)])).toEqual(want);
    }
    // One character at a time, too.
    expect(parse([...text])).toEqual(want);
  });

  it("does not split an event when \\r\\n straddles two chunks", () => {
    expect(parse(["data: x\r", "\n\r", "\n"])).toEqual([{ event: "message", data: "x", id: undefined }]);
  });

  it("joins multi-line data with newlines", () => {
    expect(parse(["data: line one\ndata: line two\ndata:\n\n"])[0].data).toBe("line one\nline two\n");
  });

  it("skips comments and keeps event names and ids", () => {
    const [m] = parse([": keep-alive\n\nevent: final\nid: 7\ndata:{}\n\n"]);
    expect(m).toEqual({ event: "final", data: "{}", id: "7" });
  });

  it("delivers a last event that lost its blank line", () => {
    expect(parse(['data: {"type":"final"}']).map((m) => m.data)).toEqual(['{"type":"final"}']);
  });

  it("strips a leading byte-order mark", () => {
    expect(parse(["﻿data: a\n\n"])[0].data).toBe("a");
  });
});

describe("sseJson", () => {
  it("yields parsed JSON and skips malformed events and [DONE]", async () => {
    const body = stream(['data: {"n":1}\n\ndata: not json\n\n', 'data: {"n"', ':2}\n\ndata: [DONE]\n\n']);
    expect(await collect(sseJson<{ n: number }>(body))).toEqual([{ n: 1 }, { n: 2 }]);
  });

  it("decodes a multi-byte character split across chunks", async () => {
    const bytes = new TextEncoder().encode('data: {"t":"₹"}\n\n');
    const cut = bytes.indexOf(0xe2) + 1; // inside the 3-byte rupee sign
    const body = stream([bytes.slice(0, cut), bytes.slice(cut)]);
    expect(await collect(sseJson<{ t: string }>(body))).toEqual([{ t: "₹" }]);
  });
});
