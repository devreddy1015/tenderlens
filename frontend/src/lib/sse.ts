/** Server-sent events, parsed by hand: EventSource can't POST, and the Copilot's /ask is a
 *  POST with a JSON body. Follows the WHATWG event-stream rules that matter to us: lines end
 *  in \n, \r\n or \r (also when a chunk splits the pair), several `data:` lines join with
 *  "\n", lines starting with ":" are comments (keep-alives), and an event ends at a blank
 *  line. A last event without its blank line is still delivered when the stream closes,
 *  because a proxy that trims the tail shouldn't cost the user the final answer. */

export interface SSEMessage {
  event: string;
  data: string;
  id?: string;
}

export function createSSEParser(onMessage: (m: SSEMessage) => void) {
  let buf = "";
  let data: string[] = [];
  let event = "";
  let id: string | undefined;
  let started = false;

  const dispatch = () => {
    if (data.length) onMessage({ event: event || "message", data: data.join("\n"), id });
    data = [];
    event = "";
  };

  const line = (l: string) => {
    if (l === "") return dispatch();
    if (l.startsWith(":")) return;
    const i = l.indexOf(":");
    const field = i < 0 ? l : l.slice(0, i);
    let value = i < 0 ? "" : l.slice(i + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") data.push(value);
    else if (field === "event") event = value;
    else if (field === "id") id = value;
  };

  return {
    push(chunk: string) {
      if (!started) {
        started = true;
        if (chunk.startsWith("﻿")) chunk = chunk.slice(1);
      }
      buf += chunk;
      let start = 0;
      for (let i = 0; i < buf.length; i++) {
        const c = buf[i];
        if (c !== "\n" && c !== "\r") continue;
        // A trailing \r may be the first half of \r\n: wait for the next chunk.
        if (c === "\r" && i === buf.length - 1) break;
        line(buf.slice(start, i));
        if (c === "\r" && buf[i + 1] === "\n") i++;
        start = i + 1;
      }
      buf = buf.slice(start);
    },
    end() {
      if (buf) line(buf.endsWith("\r") ? buf.slice(0, -1) : buf);
      buf = "";
      dispatch();
    },
  };
}

/** The JSON payload of every event of a streamed response. Malformed events are skipped
 *  rather than ending the stream. Leaving the loop early cancels the download. */
export async function* sseJson<T>(body: ReadableStream<Uint8Array>): AsyncGenerator<T> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const queue: SSEMessage[] = [];
  const parser = createSSEParser((m) => queue.push(m));
  let finished = false;
  try {
    while (!finished) {
      const { value, done } = await reader.read();
      if (done) {
        parser.push(decoder.decode());
        parser.end();
        finished = true;
      } else {
        parser.push(decoder.decode(value, { stream: true }));
      }
      while (queue.length) {
        const m = queue.shift()!;
        if (!m.data || m.data === "[DONE]") continue;
        let parsed: T;
        try {
          parsed = JSON.parse(m.data) as T;
        } catch {
          continue;
        }
        yield parsed;
      }
    }
  } finally {
    if (!finished) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
