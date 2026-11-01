// The live event stream (GET /api/events). EventSource can't send the token header, so the stream
// is read with fetch, and reconnects send Last-Event-ID to replay what was missed.

import { authHeaders } from "./api";

export interface StreamEvent {
  id: string | null;
  event: string;
  data: unknown;
}

/** Splits a text/event-stream into events. Feed it chunks as they arrive. */
export class SSEParser {
  private buf = "";

  push(chunk: string): StreamEvent[] {
    this.buf += chunk.replace(/\r\n/g, "\n");
    const out: StreamEvent[] = [];
    let i: number;
    while ((i = this.buf.indexOf("\n\n")) >= 0) {
      const block = this.buf.slice(0, i);
      this.buf = this.buf.slice(i + 2);
      let id: string | null = null;
      let event = "";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (!line || line.startsWith(":")) continue; // keep-alive comment
        const j = line.indexOf(":");
        const field = j < 0 ? line : line.slice(0, j);
        const value = j < 0 ? "" : line.slice(j + 1).replace(/^ /, "");
        if (field === "id") id = value;
        else if (field === "event") event = value;
        else if (field === "data") data.push(value);
      }
      if (!event) continue; // "retry:" only, or a comment
      let parsed: unknown = {};
      try {
        parsed = data.length ? JSON.parse(data.join("\n")) : {};
      } catch {
        continue;
      }
      out.push({ id, event, data: parsed });
    }
    return out;
  }
}

export type ConnState = "connecting" | "open" | "lost" | "unauthorized";

export interface ListenOptions {
  onEvent: (event: string, data: unknown) => void;
  onConn: (state: ConnState) => void;
  signal: AbortSignal;
  retryMs?: number;
}

/** Listens until the signal aborts, reconnecting after drops. */
export async function listen({ onEvent, onConn, signal, retryMs = 2000 }: ListenOptions) {
  let lastId: string | null = null;
  while (!signal.aborted) {
    try {
      const headers: Record<string, string> = { ...authHeaders() };
      if (lastId) headers["Last-Event-ID"] = lastId;
      const res = await fetch("/api/events", { headers, signal });
      if (res.status === 401 || res.status === 403) {
        onConn("unauthorized");
        return;
      }
      if (!res.ok || !res.body) throw new Error(`events: ${res.status}`);
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      const parser = new SSEParser();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        for (const ev of parser.push(value)) {
          if (ev.id) lastId = ev.id;
          if (ev.event === "hello") onConn("open");
          onEvent(ev.event, ev.data);
        }
      }
    } catch {
      if (signal.aborted) return;
    }
    onConn("lost");
    await new Promise((r) => setTimeout(r, retryMs));
  }
}
