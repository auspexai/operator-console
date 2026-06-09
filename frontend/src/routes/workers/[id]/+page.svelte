<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import Nav from '$lib/components/Nav.svelte';
  import LiveDot from '$lib/components/LiveDot.svelte';
  import { autoRefresh, type LiveEvent } from '$lib/live';

  // I3 (ui_triage_first_ia_redesign.md §4.4): the canonical worker record —
  // identity, state + holds (with reasons), capabilities (version / executor
  // mode / models / served_models / thermal), and ALL the worker actions
  // (quarantine, pause). The list links here; this is the one home.
  // Sourced by filtering the list endpoint (full WorkerResponse) + scheduler
  // state for eligibility — no extra proxy route needed.

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
      os?: string;
      arch?: string;
      ram_total_gb?: number;
      cpu_count?: number;
    } | null;
  };

  const tierNames: Record<number, string> = {
    0: 'T0 anonymous',
    1: 'T1 authenticated',
    2: 'T2 trusted',
    3: 'T3 vetted',
  };

  let workerId = $derived(page.params.id ?? '');
  let worker = $state<Worker | null>(null);
  let eligibleCount = $state<number | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let actionLoading = $state(false);
  let live = $state(false);

  async function load(silent = false): Promise<boolean> {
    if (!silent) loading = true;
    try {
      const [r, schedR] = await Promise.all([
        fetch('/api/v0/proxy/workers'),
        fetch('/api/v0/proxy/scheduler/state'),
      ]);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      const workers: Worker[] = body.workers || body || [];
      worker = workers.find((w) => w.worker_id === workerId) ?? null;
      if (schedR.ok) {
        const st = await schedR.json();
        const sw = (st.workers || []).find((x: { worker_id: string }) => x.worker_id === workerId);
        eligibleCount = sw ? sw.eligible_experiment_count : null;
      }
      error = null;
      return true;
    } catch (e) {
      if (!silent) error = (e as Error).message;
      return false;
    } finally {
      if (!silent) loading = false;
    }
  }

  async function action(verb: string, body: Record<string, unknown> | null, label: string) {
    actionLoading = true;
    try {
      const r = await fetch(`/api/v0/proxy/workers/${workerId}/actions/${verb}`, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : {},
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await load();
    } catch (e) {
      alert(`${label} failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  let pauseModal = $state<{ reason: string } | null>(null);
  let quarantineModal = $state<{ reason: string } | null>(null);

  function stale(w: Worker): boolean {
    return !w.last_heartbeat_at || Date.now() - new Date(w.last_heartbeat_at).getTime() > 180_000;
  }

  onMount(() => {
    load().then((ok) => (live = ok));
    return autoRefresh({
      refresh: () => load(true),
      setLive: (v) => (live = v),
      types: ['worker.status', 'network.status'],
      eventFilter: (ev: LiveEvent) =>
        (ev.data as { worker_id?: string } | null)?.worker_id === workerId,
    });
  });
</script>

<svelte:head>
  <title>Worker {workerId} — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1>
      <a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> worker detail
      {#if !loading}<LiveDot {live} />{/if}
    </h1>
  </header>
  <Nav />

  <p class="breadcrumb"><a href="/workers">workers</a> / <span class="mono">{workerId}</span></p>

  {#if loading}
    <p class="muted">Loading worker…</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else if !worker}
    <p class="muted">No worker <span class="mono">{workerId}</span> on the network.</p>
  {:else}
    <section class="card">
      <h2>Identity & state</h2>
      <dl>
        <dt>worker_id</dt><dd class="mono">{worker.worker_id}</dd>
        <dt>trust tier</dt><dd><span class="badge tier-{worker.trust_tier}">{tierNames[worker.trust_tier] ?? `T${worker.trust_tier}`}</span></dd>
        <dt>account</dt><dd class="mono">{#if worker.account_id}<a href="/accounts/{worker.account_id}" class="id-link">{worker.account_id}</a>{:else}— unbound (T0){/if}</dd>
        <dt>state</dt>
        <dd>
          {#if worker.retired_at}
            <span class="badge retired-badge">retired</span>
          {:else if worker.quarantined_at}
            <span class="badge quarantine-badge">quarantined</span>{#if worker.quarantine_reason}<span class="muted"> — {worker.quarantine_reason}</span>{/if}
          {:else if worker.paused_at}
            <span class="badge paused-badge">operator-paused (no-fault)</span>{#if worker.pause_reason}<span class="muted"> — {worker.pause_reason}</span>{/if}
          {:else if worker.capabilities?.self_paused}
            <span class="badge selfpaused-badge">self-paused</span> <span class="muted">— by the volunteer (still enrolled)</span>
          {:else if stale(worker)}
            <span class="badge stale-badge">offline</span> <span class="muted">— no recent heartbeat</span>
          {:else if worker.capabilities?.thermal?.state === 'critical'}
            <span class="badge overheating-badge">overheating</span> <span class="muted">{#if worker.capabilities?.thermal?.current_temp_c != null}— {worker.capabilities.thermal.current_temp_c}°C, {/if}routed around until cooled</span>
          {:else}
            <span class="badge ok">online</span>
          {/if}
        </dd>
        <dt>registered</dt><dd class="mono">{new Date(worker.registered_at).toLocaleString()}</dd>
        <dt>last heartbeat</dt><dd class="mono">{worker.last_heartbeat_at ? new Date(worker.last_heartbeat_at).toLocaleString() : '—'}</dd>
        <dt>eligible for</dt><dd>{eligibleCount != null ? `${eligibleCount} queued experiment(s)` : '—'}</dd>
        <dt>pubkey</dt><dd class="mono">{worker.pubkey_hex}</dd>
      </dl>
    </section>

    <section class="card">
      <h2>Capabilities</h2>
      <dl>
        <dt>worker version</dt><dd class="mono">{worker.capabilities?.worker_version ?? '—'}</dd>
        <dt>executor mode</dt>
        <dd>
          {#if (worker.capabilities?.execute_tenant_code ?? 'synthetic') === 'provisioned'}
            <span class="badge prov-b">provisioned</span> <span class="muted">— runs provisioned tenant code</span>
          {:else if worker.capabilities?.execute_tenant_code === 'off'}
            <span class="badge off-b">off</span> <span class="muted">— refuses all work</span>
          {:else}
            <span class="badge synth-b">synthetic</span> <span class="muted">— echo only; excluded from real experiments</span>
          {/if}
        </dd>
        <dt>models in store</dt>
        <dd>{#if (worker.capabilities?.models ?? []).length}<span class="mono">{(worker.capabilities?.models ?? []).join(', ')}</span>{:else}<span class="muted">none</span>{/if}</dd>
        <dt>serving (inference)</dt>
        <dd>{#if (worker.capabilities?.served_models ?? []).length}<span class="mono">{(worker.capabilities?.served_models ?? []).join(', ')}</span> <span class="badge serving-b">serve-ready</span>{:else}<span class="muted">— not an inference host</span>{/if}</dd>
        {#if worker.capabilities?.os}
          <dt>host</dt><dd class="muted">{worker.capabilities.os} / {worker.capabilities.arch}{#if worker.capabilities.ram_total_gb} · {worker.capabilities.ram_total_gb} GB RAM{/if}{#if worker.capabilities.cpu_count} · {worker.capabilities.cpu_count} CPU{/if}</dd>
        {/if}
      </dl>
    </section>

    {#if !worker.retired_at}
      <section class="card">
        <h2>Actions</h2>
        <div class="action-row">
          {#if worker.quarantined_at}
            <button onclick={() => action('unquarantine', null, 'unquarantine')} disabled={actionLoading}>unquarantine</button>
          {:else}
            <button onclick={() => (quarantineModal = { reason: '' })} disabled={actionLoading}>quarantine…</button>
          {/if}
          {#if worker.paused_at}
            <button onclick={() => action('unpause', null, 'unpause')} disabled={actionLoading}>unpause</button>
          {:else}
            <button onclick={() => (pauseModal = { reason: '' })} disabled={actionLoading}>pause…</button>
          {/if}
        </div>
        <p class="muted hint">
          <strong>quarantine</strong> = a trust/fault signal (excludes the worker + flags it).
          <strong>pause</strong> = a no-fault operational hold (offered no work; stays enrolled).
        </p>
      </section>
    {/if}
  {/if}

  {#if pauseModal}
    <div class="modal-backdrop" onclick={() => (pauseModal = null)}></div>
    <div class="modal">
      <h2>Pause worker</h2>
      <p class="mono">{workerId}</p>
      <p class="muted">No-fault operational hold — the scheduler offers it no work until unpaused. NOT a quarantine/trust mark. Reason is audited.</p>
      <label>Reason (required)
        <textarea bind:value={pauseModal.reason} rows="3" placeholder="e.g. host maintenance, rolling upgrade, investigation hold"></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (pauseModal = null)}>cancel</button>
        <button class="primary" onclick={() => { const m = pauseModal; pauseModal = null; if (m) action('pause', { reason: m.reason }, 'pause'); }} disabled={actionLoading || !pauseModal.reason.trim()}>pause</button>
      </div>
    </div>
  {/if}

  {#if quarantineModal}
    <div class="modal-backdrop" onclick={() => (quarantineModal = null)}></div>
    <div class="modal">
      <h2>Quarantine worker</h2>
      <p class="mono">{workerId}</p>
      <p class="warning">A trust/fault signal — the worker is excluded and flagged. Use pause for no-fault holds. Reason is audited.</p>
      <label>Reason (required)
        <textarea bind:value={quarantineModal.reason} rows="3" placeholder="e.g. divergent results, suspected tampering"></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (quarantineModal = null)}>cancel</button>
        <button class="danger" onclick={() => { const m = quarantineModal; quarantineModal = null; if (m) action('quarantine', { reason: m.reason }, 'quarantine'); }} disabled={actionLoading || !quarantineModal.reason.trim()}>quarantine</button>
      </div>
    </div>
  {/if}
</main>

<style>
  main { max-width: 1100px; margin: 0 auto; padding: 2em 1.25em; }
  header { border-bottom: 1px solid #2a2e3a; padding-bottom: 0.75em; margin-bottom: 1.5em; }
  h1 { margin: 0; font-size: 1.5em; font-weight: 600; color: #fff; }
  h2 { font-size: 1.05em; font-weight: 600; margin: 1.5em 0 0.5em; color: #fff; }
  .brand { color: #a78bfa; }
  .brand-link { text-decoration: none; color: inherit; }
  .breadcrumb { color: #9ca3af; font-size: 0.9em; margin-bottom: 1em; }
  .breadcrumb a { color: #a78bfa; text-decoration: none; }
  .card { background: #11152b; border: 1px solid #1e2340; border-radius: 12px; padding: 1em 1.25em; margin: 1em 0; }
  .card h2 { margin-top: 0; }
  dl { display: grid; grid-template-columns: 14em 1fr; gap: 0.3em 1em; }
  dt { color: #9ca3af; }
  dd { margin: 0; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; word-break: break-all; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.ok { background: #14532d; color: #86efac; }
  .quarantine-badge { background: #7f1d1d; color: #fca5a5; }
  .paused-badge { background: #374151; color: #d4d4dc; }
  .overheating-badge { background: #7c2d12; color: #fdba74; }
  .selfpaused-badge { background: #1e3a5f; color: #93c5fd; }
  .retired-badge { background: #374151; color: #6b7280; }
  .stale-badge { background: #78350f; color: #fbbf24; }
  .badge.tier-0 { background: #1f2937; }
  .badge.tier-1 { background: #1e3a5f; color: #93c5fd; }
  .badge.tier-2 { background: #14532d; color: #86efac; }
  .badge.tier-3 { background: #4c1d95; color: #c4b5fd; }
  .badge.prov-b { background: #14532d; color: #86efac; }
  .badge.synth-b { background: #1f2937; color: #9ca3af; }
  .badge.off-b { background: #7f1d1d; color: #fca5a5; }
  .badge.serving-b { background: #1e3a5f; color: #93c5fd; margin-left: 0.3em; }
  .id-link { color: #a78bfa; text-decoration: none; }
  .id-link:hover { text-decoration: underline; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .hint { margin-top: 0.75em; }
  .errortext { color: #fca5a5; }
  .action-row { display: flex; gap: 0.5em; flex-wrap: wrap; align-items: center; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.35em 0.75em; border-radius: 4px; cursor: pointer; font: inherit; font-size: 0.85em; }
  button:hover { background: #2a2e3a; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  button.primary { background: #a78bfa; color: #0a0e1a; border-color: #a78bfa; font-weight: 600; }
  button.danger { background: #7f1d1d; border-color: #7f1d1d; color: #fca5a5; }
  .modal-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); z-index: 10; }
  .modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #1a1e2a; border: 1px solid #2a2e3a; border-radius: 8px; padding: 1.5em; z-index: 11; width: 90%; max-width: 460px; }
  .modal h2 { margin: 0 0 0.5em; color: #fff; font-size: 1.1em; }
  .modal label { display: block; margin: 0.75em 0 0.25em; color: #9ca3af; font-size: 0.9em; }
  .modal textarea { width: 100%; padding: 0.4em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; resize: vertical; }
  .warning { background: #422006; border: 1px solid #854d0e; color: #fde68a; border-radius: 6px; padding: 0.6em 0.8em; font-size: 0.85em; margin: 0.75em 0 0; }
  .modal-actions { display: flex; gap: 0.75em; justify-content: flex-end; margin-top: 1.25em; }
</style>
