<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';
  import { autoRefresh } from '$lib/live';
  import LiveDot from '$lib/components/LiveDot.svelte';

  type Worker = {
    worker_id: string;
    pubkey_hex: string;
    account_id: string | null;
    trust_tier: number;
    registered_at: string;
    last_heartbeat_at: string | null;
    retired_at: string | null;
    quarantined_at: string | null;
    quarantine_reason: string | null;
    paused_at: string | null;
    pause_reason: string | null;
    capabilities?: {
      thermal?: { state?: string; current_temp_c?: number };
      self_paused?: boolean;
      worker_version?: string;
      execute_tenant_code?: string;
      models?: string[];
      served_models?: string[];
      downloads?: Record<string, { bytes_downloaded?: number; total_bytes?: number | null }>;
    } | null;
  };

  // Eligibility/scheduling view per worker (folded in from the dissolved
  // /scheduler, I2): how many queued experiments this worker can currently take.
  type SchedWorker = {
    worker_id: string;
    model_count: number;
    eligible_experiment_count: number;
  };

  const tierNames: Record<number, string> = {
    0: 'T0 anonymous',
    1: 'T1 authenticated',
    2: 'T2 trusted',
    3: 'T3 vetted',
  };

  let workers = $state<Worker[]>([]);
  let sched = $state<Record<string, SchedWorker>>({});
  let loading = $state(true);
  let error = $state<string | null>(null);
  let live = $state(false);

  async function loadWorkers(silent = false): Promise<boolean> {
    if (!silent) loading = true;
    try {
      // /workers is the canonical worker record; scheduler/state adds the
      // eligibility columns (best-effort — a blip there must not blank the page).
      const [r, schedR] = await Promise.all([
        fetch('/api/v0/proxy/workers'),
        fetch('/api/v0/proxy/scheduler/state'),
      ]);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      // Standing rule: newest first — most recently active worker at the top.
      workers = ((body.workers || body || []) as { last_heartbeat_at: string | null }[]).sort(
        (a, b) => (b.last_heartbeat_at ?? '').localeCompare(a.last_heartbeat_at ?? ''),
      ) as typeof workers;
      if (schedR.ok) {
        const st = await schedR.json();
        const map: Record<string, SchedWorker> = {};
        for (const sw of st.workers || []) map[sw.worker_id] = sw;
        sched = map;
      }
      error = null;
      return true;
    } catch (e) {
      // Silent (poll) failures don't replace the page with an error banner — the
      // last-good data stays and the indicator flips to "● stale".
      if (!silent) error = (e as Error).message;
      return false;
    } finally {
      if (!silent) loading = false;
    }
  }

  function execMode(w: Worker): string {
    return w.capabilities?.execute_tenant_code ?? 'synthetic';
  }

  // D12 5c: in-flight model downloads (auto-acquire). Gives the operator a live
  // "downloading <model> NN%" instead of a silent "provisioned" while a multi-GB
  // pull runs for minutes.
  function hasDownloads(w: Worker): boolean {
    return Object.keys(w.capabilities?.downloads ?? {}).length > 0;
  }
  function fmtBytes(n: number): string {
    return n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.round(n / 1e6)} MB`;
  }
  function downloadSummary(w: Worker): string {
    const dl = w.capabilities?.downloads ?? {};
    return Object.entries(dl)
      .map(([mid, p]) => {
        const done = p.bytes_downloaded ?? 0;
        if (p.total_bytes && p.total_bytes > 0) {
          const pct = Math.min(100, Math.floor((done / p.total_bytes) * 100));
          return `downloading ${mid} ${pct}% (${fmtBytes(done)}/${fmtBytes(p.total_bytes)})`;
        }
        return `downloading ${mid} ${fmtBytes(done)}`;
      })
      .join(', ');
  }

  async function quarantine(workerId: string) {
    const reason = prompt('Quarantine reason (optional):');
    try {
      await fetch(`/api/v0/proxy/workers/${workerId}/actions/quarantine`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });
      await loadWorkers();
    } catch (e) {
      alert(`Failed: ${(e as Error).message}`);
    }
  }

  async function unquarantine(workerId: string) {
    try {
      await fetch(`/api/v0/proxy/workers/${workerId}/actions/unquarantine`, {
        method: 'POST',
      });
      await loadWorkers();
    } catch (e) {
      alert(`Failed: ${(e as Error).message}`);
    }
  }

  async function pause(workerId: string) {
    // No-fault operational hold (not a quarantine/trust signal). Reason is
    // mandatory + audited.
    const reason = prompt('Pause reason (required) — e.g. host maintenance, rolling upgrade:');
    if (!reason || !reason.trim()) return;
    try {
      const r = await fetch(`/api/v0/proxy/workers/${workerId}/actions/pause`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await loadWorkers();
    } catch (e) {
      alert(`Failed: ${(e as Error).message}`);
    }
  }

  async function unpause(workerId: string) {
    try {
      await fetch(`/api/v0/proxy/workers/${workerId}/actions/unpause`, { method: 'POST' });
      await loadWorkers();
    } catch (e) {
      alert(`Failed: ${(e as Error).message}`);
    }
  }

  onMount(() => {
    loadWorkers().then((ok) => (live = ok));
    // Poll is the truth, the SSE doorbell is a hint. A worker heartbeat emits no
    // event, so the baseline poll keeps "last heartbeat" / online-offline /
    // thermal honest; worker.status nudges an instant re-snapshot on operator
    // transitions (quarantine/pause/retire/…).
    return autoRefresh({
      refresh: () => loadWorkers(true),
      setLive: (v) => (live = v),
      types: ['worker.status', 'network.status'],
    });
  });
</script>

<svelte:head>
  <title>Workers — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> workers fleet
      {#if !loading}<LiveDot {live} />{/if}
    </h1>
  </header>
  <Nav />

  {#if loading}
    <p class="muted">Loading workers…</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else if workers.length === 0}
    <p class="muted">No workers enrolled.</p>
  {:else}
    <table>
      <thead>
        <tr>
          <th>worker_id</th>
          <th>tier</th>
          <th>executor</th>
          <th>version</th>
          <th>models</th>
          <th>eligible for</th>
          <th>last heartbeat</th>
          <th>status</th>
          <th>actions</th>
        </tr>
      </thead>
      <tbody>
        {#each workers as w}
          <tr class:quarantined={!!w.quarantined_at} class:retired={!!w.retired_at} class:paused={!!w.paused_at}>
            <td class="mono"><a href="/workers/{w.worker_id}" class="id-link">{w.worker_id}</a></td>
            <td><span class="badge tier-{w.trust_tier}">{tierNames[w.trust_tier] ?? `T${w.trust_tier}`}</span></td>
            <td>
              {#if execMode(w) === 'provisioned'}
                <span class="badge prov-b" title="runs provisioned tenant code — eligible for real (model-gated) experiments">provisioned</span>
              {:else if execMode(w) === 'off'}
                <span class="badge off-b" title="refuses all work">off</span>
              {:else}
                <span class="badge synth-b" title="synthetic echo only — excluded from real (model-gated) experiments">synthetic</span>
              {/if}
            </td>
            <td class="mono">{w.capabilities?.worker_version ?? '—'}</td>
            <td>
              {(w.capabilities?.models ?? []).length}
              {#if (w.capabilities?.served_models ?? []).length > 0}
                <span class="badge serving-b" title="loaded + serve-ready in the inference backend: {(w.capabilities?.served_models ?? []).join(', ')}">{(w.capabilities?.served_models ?? []).length} serving</span>
              {/if}
            </td>
            <td>
              {#if sched[w.worker_id]}
                {sched[w.worker_id].eligible_experiment_count} exp{#if sched[w.worker_id].eligible_experiment_count === 0 && !w.paused_at && !w.quarantined_at}<span class="badge idle"> idle</span>{/if}
              {:else}
                <span class="muted">—</span>
              {/if}
            </td>
            <td class="mono">{w.last_heartbeat_at ? new Date(w.last_heartbeat_at).toLocaleString() : '—'}</td>
            <td>
              {#if w.retired_at}
                <span class="badge retired-badge">retired</span>
              {:else if w.quarantined_at}
                <span class="badge quarantine-badge">quarantined</span>
                {#if w.quarantine_reason}
                  <span class="muted"> — {w.quarantine_reason}</span>
                {/if}
              {:else if w.paused_at}
                <span class="badge paused-badge">paused</span>
                <span class="muted"> — operator hold (no-fault){#if w.pause_reason}: {w.pause_reason}{/if}</span>
              {:else if w.capabilities?.self_paused}
                <span class="badge selfpaused-badge">self-paused</span>
                <span class="muted"> — paused by the volunteer (still enrolled)</span>
              {:else if !w.last_heartbeat_at || (Date.now() - new Date(w.last_heartbeat_at).getTime()) > 180_000}
                <span class="badge stale-badge">offline</span>
              {:else if w.capabilities?.thermal?.state === 'critical'}
                <span class="badge overheating-badge">overheating</span>
                <span class="muted">
                  {#if w.capabilities?.thermal?.current_temp_c != null}— {w.capabilities.thermal.current_temp_c}°C, {/if}routed around until cooled
                </span>
              {:else if hasDownloads(w)}
                <span class="badge downloading-badge">provisioning</span>
                <span class="muted"> — {downloadSummary(w)}</span>
              {:else}
                <span class="badge ok">online</span>
              {/if}
            </td>
            <td class="actions">
              {#if !w.retired_at}
                {#if w.quarantined_at}
                  <button onclick={() => unquarantine(w.worker_id)}>unquarantine</button>
                {:else}
                  <button onclick={() => quarantine(w.worker_id)}>quarantine</button>
                {/if}
                {#if w.paused_at}
                  <button onclick={() => unpause(w.worker_id)}>unpause</button>
                {:else}
                  <button onclick={() => pause(w.worker_id)}>pause</button>
                {/if}
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p class="muted">{workers.length} worker(s)</p>
  {/if}
</main>

<style>
  main { max-width: 1100px; margin: 0 auto; padding: 2em 1.25em; }
  header { border-bottom: 1px solid #2a2e3a; padding-bottom: 0.75em; margin-bottom: 1.5em; }
  h1 { margin: 0; font-size: 1.5em; font-weight: 600; color: #fff; }
  .brand { color: #a78bfa; }
  .brand-link { text-decoration: none; color: inherit; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
  th { text-align: left; padding: 0.5em; border-bottom: 2px solid #2a2e3a; color: #9ca3af; font-weight: 500; }
  td { padding: 0.5em; border-bottom: 1px solid #1a1e2a; }
  tr.quarantined { background: rgba(127, 29, 29, 0.15); }
  tr.paused { background: rgba(55, 65, 81, 0.25); }
  tr.retired { opacity: 0.5; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.ok { background: #14532d; color: #86efac; }
  .quarantine-badge { background: #7f1d1d; color: #fca5a5; }
  .paused-badge { background: #374151; color: #d4d4dc; }
  .overheating-badge { background: #7c2d12; color: #fdba74; }
  .selfpaused-badge { background: #1e3a5f; color: #93c5fd; }
  .retired-badge { background: #374151; color: #6b7280; }
  .actions { white-space: nowrap; }
  .stale-badge { background: #78350f; color: #fbbf24; }
  .downloading-badge { background: #1e3a5f; color: #93c5fd; }
  /* tier = neutral text (no chip); color is reserved for actions. */
  .badge.tier-0, .badge.tier-1, .badge.tier-2, .badge.tier-3 {
    background: transparent;
    padding: 0;
    font-weight: 400;
    color: #c9ced9;
  }
  .badge.prov-b { background: #14532d; color: #86efac; }
  .badge.synth-b { background: #1f2937; color: #9ca3af; }
  .badge.off-b { background: #7f1d1d; color: #fca5a5; }
  .badge.serving-b { background: #1e3a5f; color: #93c5fd; margin-left: 0.3em; }
  .badge.idle { background: #78350f; color: #fcd34d; margin-left: 0.3em; }
  .id-link { color: #a78bfa; text-decoration: none; }
  .id-link:hover { text-decoration: underline; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.25em 0.65em; border-radius: 4px; cursor: pointer; font: inherit; font-size: 0.85em; }
  button:hover { background: #2a2e3a; }
</style>
