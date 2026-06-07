// Live event stream (M6): subscribe to the coordinator maintainer firehose,
// proxied by the console backend at /api/v0/proxy/events (the browser can't sign
// coordinator requests; the session cookie rides same-origin to the proxy).
//
// Snapshot-then-tail (design note §5): the caller REST-snapshots first, then calls
// this and re-snapshots on each relevant event + on reconnect (gap-safe — the bus
// is lossy, so the poll/snapshot is the source of truth, the stream is the nudge).
// Generic by design so workers/scheduler pages reuse it; the researcher dashboard
// reuses the same shape against its tenant-scoped endpoint.

export type LiveEvent = { type: string; data: unknown };

export type FirehoseOptions = {
  /** Named SSE event types to listen for (the coordinator sets `event: <type>`).
   *  EventSource only routes named events to per-type listeners, not onmessage. */
  types: string[];
  onEvent: (ev: LiveEvent) => void;
  /** Called on a reconnect (not the first open) so the caller can re-snapshot
   *  whatever it missed while disconnected. */
  onReconnect?: () => void;
  /** Connection state, for a live indicator. `onOpen` fires on first connect and
   *  every reconnect; `onError` fires when the connection drops. */
  onOpen?: () => void;
  onError?: () => void;
};

/** Open the firehose. Returns a close function (call it on component teardown).
 *  EventSource reconnects automatically on drop. */
export function subscribeFirehose(opts: FirehoseOptions): () => void {
  const es = new EventSource('/api/v0/proxy/events');
  let opened = false;
  es.onopen = () => {
    opts.onOpen?.();
    if (opened) opts.onReconnect?.();
    opened = true;
  };
  es.onerror = () => opts.onError?.();
  for (const type of opts.types) {
    es.addEventListener(type, (e) => {
      let data: unknown = null;
      try {
        data = JSON.parse((e as MessageEvent).data);
      } catch {
        /* keep null — the type alone is enough to trigger a re-snapshot */
      }
      opts.onEvent({ type, data });
    });
  }
  return () => es.close();
}
