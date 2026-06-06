<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';

  type ModelRequest = {
    request_id: string;
    tenant_id: string;
    model_id: string;
    hf_repo: string | null;
    reason: string;
    status: string; // available | pending | fulfilled | declined
    created_at: string;
    resolved_at: string | null;
    resolved_by: string | null;
    resolution_reason: string | null;
  };

  type SchedExp = {
    experiment_id: string;
    tenant_id: string;
    tenant_experiment_label: string;
    pending: number;
    in_progress: number;
    completed: number;
    required_capabilities: Record<string, string[]>;
    capable_worker_count: number;
    eligible_worker_count: number;
    blocked: boolean;
    block_reason: string | null;
    stalled_units?: number;
  };

  type SchedWorker = {
    worker_id: string;
    trust_tier: number;
    model_count: number;
    paused: boolean;
    degraded?: boolean;
    self_paused?: boolean;
    eligible_experiment_count: number;
  };

  type CatalogEntry = { model_id: string; worker_count: number };

  let requests = $state<ModelRequest[]>([]);
  let experiments = $state<SchedExp[]>([]);
  let workers = $state<SchedWorker[]>([]);
  let activeWorkers = $state(0);
  let catalog = $state<CatalogEntry[]>([]);
  let catalogTotal = $state(0);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let actionLoading = $state(false);

  let resolveModal = $state<{ requestId: string; modelId: string; action: 'fulfil' | 'decline'; reason: string } | null>(null);
  let pauseModal = $state<{ workerId: string; reason: string } | null>(null);
  let policyModal = $state<{ experimentId: string; label: string; policy: string; reason: string } | null>(null);
  let prestageModal = $state<{ experimentId: string; label: string; reason: string } | null>(null);

  async function loadAll() {
    loading = true;
    error = null;
    try {
      const [stateR, catR, reqR] = await Promise.all([
        fetch('/api/v0/proxy/scheduler/state'),
        fetch('/api/v0/proxy/models/catalog'),
        fetch('/api/v0/proxy/model-requests'),
      ]);
      if (!stateR.ok) throw new Error(`scheduler/state HTTP ${stateR.status}`);
      const st = await stateR.json();
      experiments = st.experiments || [];
      workers = st.workers || [];
      activeWorkers = st.active_worker_count ?? 0;
      if (catR.ok) {
        const c = await catR.json();
        catalog = c.models || [];
        catalogTotal = c.total_active_workers ?? 0;
      }
      if (reqR.ok) requests = (await reqR.json()).requests || [];
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  async function post(path: string, body: unknown | null, onErr: string) {
    actionLoading = true;
    try {
      const r = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body === null ? undefined : JSON.stringify(body),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(JSON.stringify(d));
      }
      await loadAll();
    } catch (e) {
      alert(`${onErr} failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  async function submitResolve() {
    if (!resolveModal) return;
    const m = resolveModal;
    resolveModal = null;
    await post(`/api/v0/proxy/model-requests/${m.requestId}/actions/${m.action}`, { reason: m.reason }, m.action);
  }
  async function submitPause() {
    if (!pauseModal) return;
    const m = pauseModal;
    pauseModal = null;
    await post(`/api/v0/proxy/workers/${m.workerId}/actions/pause`, { reason: m.reason }, 'pause');
  }
  async function unpause(workerId: string) {
    await post(`/api/v0/proxy/workers/${workerId}/actions/unpause`, null, 'unpause');
  }
  async function submitPolicy() {
    if (!policyModal) return;
    const m = policyModal;
    policyModal = null;
    await post(`/api/v0/proxy/experiments/${m.experimentId}/actions/set-integrity-policy`, { integrity_policy: m.policy, reason: m.reason }, 'set policy');
  }

  async function submitPrestage() {
    if (!prestageModal) return;
    const m = prestageModal;
    prestageModal = null;
    await post(`/api/v0/proxy/experiments/${m.experimentId}/actions/trigger-prestage`, { reason: m.reason }, 'trigger pre-stage');
  }

  const reqOrder: Record<string, number> = { pending: 0, available: 1, fulfilled: 2, declined: 3 };
  let sortedReqs = $derived([...requests].sort((a, b) => (reqOrder[a.status] ?? 9) - (reqOrder[b.status] ?? 9) || b.created_at.localeCompare(a.created_at)));
  let blockedExps = $derived(experiments.filter((e) => e.blocked));
  let pendingReqs = $derived(requests.filter((r) => r.status === 'pending').length);

  function models(caps: Record<string, string[]>): string {
    return (caps?.models || []).join(', ');
  }

  onMount(loadAll);
</script>

<svelte:head>
  <title>Scheduler — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> scheduler</h1>
  </header>
  <Nav />

  <p class="muted">
    How the scheduler matches supply (workers + their models) to demand (pending work).
    {#if !loading}<strong>{activeWorkers}</strong> worker(s) available · <strong>{blockedExps.length}</strong> blocked experiment(s) · <strong>{pendingReqs}</strong> pending model request(s).{/if}
  </p>

  {#if loading}
    <p class="muted">Loading scheduler state…</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else}
    <!-- 1. Blocked / starved triage -->
    <h2 class="section">Experiments &amp; assignment</h2>
    <p class="muted">Approved experiments with outstanding work. <strong>blocked</strong> = units that can't land on any available worker (with why).</p>
    {#if experiments.length === 0}
      <p class="muted">No approved experiments with work.</p>
    {:else}
      <table>
        <thead><tr><th>experiment</th><th>tenant</th><th>pending</th><th>in&nbsp;prog</th><th>done</th><th>requires</th><th>capable / eligible</th><th>status</th><th>actions</th></tr></thead>
        <tbody>
          {#each experiments as e}
            <tr class:blocked={e.blocked}>
              <td class="mono">{e.tenant_experiment_label}<br /><span class="muted">{e.experiment_id}</span></td>
              <td class="mono">{e.tenant_id}</td>
              <td>{e.pending}</td>
              <td>{e.in_progress}</td>
              <td>{e.completed}</td>
              <td class="mono">{models(e.required_capabilities) || '—'}</td>
              <td>{e.capable_worker_count} / {e.eligible_worker_count}</td>
              <td>
                {#if e.blocked}<span class="badge block">blocked: {e.block_reason}</span>{:else}<span class="badge ok">ok</span>{/if}
                {#if e.stalled_units}<span class="badge stalled" title="in-progress units stranded — every worker refused non-reofferably">{e.stalled_units} stalled</span>{/if}
              </td>
              <td class="actions">
                <button onclick={() => (policyModal = { experimentId: e.experiment_id, label: e.tenant_experiment_label, policy: 'standard', reason: '' })} disabled={actionLoading}>set policy</button>
                <button onclick={() => (prestageModal = { experimentId: e.experiment_id, label: e.tenant_experiment_label, reason: '' })} disabled={actionLoading}>pre-stage</button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}

    <!-- 2. Workers eligibility / idleness -->
    <h2 class="section">Workers</h2>
    <p class="muted">On-network workers and what they can take. <strong>idle</strong> = eligible for nothing currently queued. <strong>pause</strong> = no-fault operational hold (offered no work; stays enrolled). <strong>overheating</strong> = thermal-critical (W-H); routed around until it cools.</p>
    {#if workers.length === 0}
      <p class="muted">No workers on the network.</p>
    {:else}
      <table>
        <thead><tr><th>worker_id</th><th>tier</th><th>models</th><th>eligible for</th><th>state</th><th>actions</th></tr></thead>
        <tbody>
          {#each workers as w}
            <tr class:paused={w.paused || w.degraded || w.self_paused}>
              <td class="mono">{w.worker_id}</td>
              <td><span class="badge tier-{w.trust_tier}">T{w.trust_tier}</span></td>
              <td>{w.model_count}</td>
              <td>{w.eligible_experiment_count} exp{#if w.eligible_experiment_count === 0 && !w.paused && !w.degraded && !w.self_paused}<span class="badge idle"> idle</span>{/if}</td>
              <td>{#if w.paused}<span class="badge paused-b">paused</span>{:else if w.self_paused}<span class="badge selfpaused-b">self-paused</span>{:else if w.degraded}<span class="badge degraded-b">overheating</span>{:else}<span class="badge ok">active</span>{/if}</td>
              <td class="actions">
                {#if w.paused}
                  <button onclick={() => unpause(w.worker_id)} disabled={actionLoading}>unpause</button>
                {:else}
                  <button onclick={() => (pauseModal = { workerId: w.worker_id, reason: '' })} disabled={actionLoading}>pause</button>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}

    <!-- 3. Network model catalog -->
    <h2 class="section">Network model catalog</h2>
    <p class="muted">What the fleet can run — the bottom-up aggregate of models active workers hold ({catalogTotal} worker(s)).</p>
    {#if catalog.length === 0}
      <p class="muted">No models available on the network.</p>
    {:else}
      <table>
        <thead><tr><th>model_id</th><th>workers</th></tr></thead>
        <tbody>
          {#each catalog as m}
            <tr><td class="mono">{m.model_id}</td><td>{m.worker_count}</td></tr>
          {/each}
        </tbody>
      </table>
    {/if}

    <!-- 0. New-requirement queue -->
    <h2 class="section">New-requirement queue</h2>
    <p class="muted">Researcher demand for models (BYOM). <strong>pending</strong> = no active worker holds it — recruit a volunteer then <em>fulfil</em>, or <em>decline</em>.</p>
    {#if requests.length === 0}
      <p class="muted">No model requests yet.</p>
    {:else}
      <table>
        <thead><tr><th>model_id</th><th>tenant</th><th>reason</th><th>status</th><th>created</th><th>resolution</th><th>actions</th></tr></thead>
        <tbody>
          {#each sortedReqs as req}
            <tr class:pending={req.status === 'pending'}>
              <td class="mono">{req.model_id}{#if req.hf_repo}<br /><span class="muted">{req.hf_repo}</span>{/if}</td>
              <td class="mono">{req.tenant_id}</td>
              <td class="reason">{req.reason}</td>
              <td><span class="badge status-{req.status}">{req.status}</span></td>
              <td class="mono">{new Date(req.created_at).toLocaleString()}</td>
              <td>{#if req.resolved_at}<span class="muted">{req.resolved_by ?? '—'}: {req.resolution_reason ?? ''}</span>{:else}<span class="muted">—</span>{/if}</td>
              <td class="actions">
                {#if req.status === 'pending'}
                  <button class="primary" onclick={() => (resolveModal = { requestId: req.request_id, modelId: req.model_id, action: 'fulfil', reason: '' })} disabled={actionLoading}>fulfil</button>
                  <button class="danger" onclick={() => (resolveModal = { requestId: req.request_id, modelId: req.model_id, action: 'decline', reason: '' })} disabled={actionLoading}>decline</button>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  {/if}

  {#if resolveModal}
    <div class="modal-backdrop" onclick={() => (resolveModal = null)}></div>
    <div class="tier-modal">
      <h2>{resolveModal.action === 'fulfil' ? 'Fulfil' : 'Decline'} model request</h2>
      <p class="mono">{resolveModal.modelId}</p>
      <label>Reason (required)
        <textarea bind:value={resolveModal.reason} rows="3" placeholder="recorded in the audit log"></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (resolveModal = null)}>cancel</button>
        <button class={resolveModal.action === 'fulfil' ? 'primary' : 'danger'} onclick={submitResolve} disabled={actionLoading || !resolveModal.reason.trim()}>{resolveModal.action}</button>
      </div>
    </div>
  {/if}

  {#if pauseModal}
    <div class="modal-backdrop" onclick={() => (pauseModal = null)}></div>
    <div class="tier-modal">
      <h2>Pause worker</h2>
      <p class="mono">{pauseModal.workerId}</p>
      <p class="muted">No-fault operational hold — the scheduler offers it no work until unpaused. NOT a quarantine/trust mark. Reason is audited.</p>
      <label>Reason (required)
        <textarea bind:value={pauseModal.reason} rows="3" placeholder="e.g., host maintenance, rolling upgrade, investigation hold"></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (pauseModal = null)}>cancel</button>
        <button class="primary" onclick={submitPause} disabled={actionLoading || !pauseModal.reason.trim()}>pause</button>
      </div>
    </div>
  {/if}

  {#if policyModal}
    <div class="modal-backdrop" onclick={() => (policyModal = null)}></div>
    <div class="tier-modal">
      <h2>Set integrity policy</h2>
      <p class="mono">{policyModal.label}</p>
      <p class="warn-text">Affects FUTURE units only — units already submitted keep their replication target.</p>
      <label>Policy
        <select bind:value={policyModal.policy}>
          <option value="standard">standard (replication 3)</option>
          <option value="high">high (replication 5)</option>
          <option value="trusted">trusted (replication 1; T2+ only)</option>
        </select>
      </label>
      <label>Reason (required)
        <textarea bind:value={policyModal.reason} rows="3" placeholder="recorded in the audit log"></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (policyModal = null)}>cancel</button>
        <button class="primary" onclick={submitPolicy} disabled={actionLoading || !policyModal.reason.trim()}>set policy</button>
      </div>
    </div>
  {/if}

  {#if prestageModal}
    <div class="modal-backdrop" onclick={() => (prestageModal = null)}></div>
    <div class="tier-modal">
      <h2>Trigger pre-stage</h2>
      <p class="mono">{prestageModal.label}</p>
      <p class="muted">Eagerly pulls this experiment's required model(s) onto eligible auto-acquire workers now (bounded by the replication need), so its units aren't bottlenecked on first-assignment pulls.</p>
      <label>Reason (required)
        <textarea bind:value={prestageModal.reason} rows="3" placeholder="recorded in the audit log"></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (prestageModal = null)}>cancel</button>
        <button class="primary" onclick={submitPrestage} disabled={actionLoading || !prestageModal.reason.trim()}>pre-stage</button>
      </div>
    </div>
  {/if}
</main>

<style>
  main { max-width: 1100px; margin: 0 auto; padding: 2em 1.25em; }
  header { border-bottom: 1px solid #2a2e3a; padding-bottom: 0.75em; margin-bottom: 1.5em; }
  h1 { margin: 0; font-size: 1.5em; font-weight: 600; color: #fff; }
  h2.section { margin: 1.75em 0 0.25em; font-size: 1.1em; font-weight: 600; color: #d4d4dc; border-bottom: 1px solid #2a2e3a; padding-bottom: 0.3em; }
  .brand { color: #a78bfa; }
  .brand-link { text-decoration: none; color: inherit; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
  th { text-align: left; padding: 0.5em; border-bottom: 2px solid #2a2e3a; color: #9ca3af; font-weight: 500; }
  td { padding: 0.5em; border-bottom: 1px solid #1a1e2a; vertical-align: top; }
  tr.pending { background: rgba(120, 90, 10, 0.12); }
  tr.blocked { background: rgba(127, 29, 29, 0.15); }
  tr.paused { opacity: 0.6; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .reason { max-width: 260px; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.ok { background: #14532d; color: #86efac; }
  .badge.block { background: #7f1d1d; color: #fca5a5; }
  .badge.idle { background: #78350f; color: #fcd34d; margin-left: 0.3em; }
  .badge.degraded-b { background: #7c2d12; color: #fdba74; }
  .badge.selfpaused-b { background: #1e3a5f; color: #93c5fd; }
  .badge.stalled { background: #78350f; color: #fcd34d; margin-left: 0.3em; }
  .badge.paused-b { background: #374151; color: #d4d4dc; }
  .badge.tier-0 { background: #1f2937; }
  .badge.tier-1 { background: #1e3a5f; color: #93c5fd; }
  .badge.tier-2 { background: #14532d; color: #86efac; }
  .badge.tier-3 { background: #4c1d95; color: #c4b5fd; }
  .status-pending { background: #78350f; color: #fcd34d; }
  .status-available { background: #1e3a5f; color: #93c5fd; }
  .status-fulfilled { background: #14532d; color: #86efac; }
  .status-declined { background: #374151; color: #9ca3af; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  .actions { white-space: nowrap; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.25em 0.65em; border-radius: 4px; cursor: pointer; font: inherit; font-size: 0.85em; }
  button:hover { background: #2a2e3a; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  button.primary { background: #a78bfa; color: #0a0e1a; border-color: #a78bfa; font-weight: 600; }
  button.primary:hover { background: #c4b5fd; }
  button.danger { background: #7f1d1d; border-color: #7f1d1d; color: #fca5a5; }
  button.danger:hover { background: #991b1b; }
  .modal-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); z-index: 10; }
  .tier-modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #1a1e2a; border: 1px solid #2a2e3a; border-radius: 8px; padding: 1.5em; z-index: 11; width: 90%; max-width: 500px; }
  .tier-modal h2 { margin: 0 0 0.5em; color: #fff; font-size: 1.1em; }
  .tier-modal label { display: block; margin: 0.75em 0 0.25em; color: #9ca3af; font-size: 0.9em; }
  .tier-modal textarea, .tier-modal select { width: 100%; padding: 0.4em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; font-size: 0.9em; resize: vertical; }
  .tier-modal textarea:focus, .tier-modal select:focus { outline: none; border-color: #a78bfa; }
  .modal-actions { display: flex; gap: 0.75em; justify-content: flex-end; margin-top: 1.25em; }
  .warn-text { color: #fbbf24; font-size: 0.9em; margin: 0.25em 0 0.5em; }
</style>
