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

export type AutoRefreshOptions = {
  /** Re-snapshot the page's data. Resolve `true` on success, `false` on failure
   *  (throwing is also treated as failure). Drives the live/stale indicator. */
  refresh: () => Promise<boolean>;
  /** Receives the live state after each refresh (true = ok, false = failed). */
  setLive: (live: boolean) => void;
  /** Firehose event types that should trigger an *immediate* re-snapshot (the
   *  doorbell). Omit/empty for poll-only pages (no relevant live events). */
  types?: string[];
  /** Baseline poll interval in ms. Default 30s — the floor of liveness even when
   *  no event ever fires (heartbeat age, offline detection, thermal, progress). */
  intervalMs?: number;
  /** Optional doorbell predicate. When given, a firehose event only triggers an
   *  immediate re-snapshot if this returns true — so a *detail* page can scope to
   *  its own experiment/account id instead of re-snapshotting on every event.
   *  Reconnect always re-snapshots regardless (gap recovery). */
  eventFilter?: (ev: LiveEvent) => boolean;
};

/**
 * Complete the M8 principle on a console page: **the poll is the source of
 * truth; the SSE doorbell is only a hint to poll sooner.**
 *
 *   - A baseline `setInterval` re-snapshot every `intervalMs` keeps *continuous*
 *     telemetry honest — heartbeat age, online/offline, thermal, progress — none
 *     of which emit a per-tick event.
 *   - (Optional) an immediate re-snapshot on each firehose event + on reconnect,
 *     so *discrete* transitions (approve/pause/quarantine/…) show up instantly.
 *
 * `live` reflects whether the most recent refresh succeeded, so the shared
 * indicator reads "● live" when updates are flowing and "● stale" when the poll
 * is failing — the same meaning on every page (events present or not).
 *
 * Returns a teardown; return it from the component's `onMount`.
 */
export function autoRefresh(opts: AutoRefreshOptions): () => void {
  const { refresh, setLive, types = [], intervalMs = 30_000, eventFilter } = opts;
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    try {
      setLive(await refresh());
    } catch {
      setLive(false);
    }
  };
  const timer: ReturnType<typeof setInterval> = setInterval(tick, intervalMs);
  let unsub: () => void = () => {};
  if (types.length > 0) {
    unsub = subscribeFirehose({
      types,
      onEvent: (ev) => {
        if (!eventFilter || eventFilter(ev)) void tick();
      },
      onReconnect: () => void tick(),
    });
  }
  return () => {
    stopped = true;
    clearInterval(timer);
    unsub();
  };
}
