<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';
  import { autoRefresh } from '$lib/live';
  import LiveDot from '$lib/components/LiveDot.svelte';

  // I2 (ui_triage_first_ia_redesign.md §4.3): the model-centric half of the
  // dissolved /scheduler — the bottom-up network catalog + the new-requirement
  // (BYOM demand) queue with its fulfil/decline actions. Worker eligibility
  // moved to /workers; experiment-centric actions (set-policy, pre-stage)
  // moved to the experiment record.

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

  type CatalogEntry = { model_id: string; worker_count: number };

  let requests = $state<ModelRequest[]>([]);
  let catalog = $state<CatalogEntry[]>([]);
  let catalogTotal = $state(0);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let actionLoading = $state(false);
  let live = $state(false);

  let resolveModal = $state<{
    requestId: string;
    modelId: string;
    action: 'fulfil' | 'decline';
    reason: string;
  } | null>(null);

  async function loadAll(silent = false): Promise<boolean> {
    if (!silent) loading = true;
    try {
      const [catR, reqR] = await Promise.all([
        fetch('/api/v0/proxy/models/catalog'),
        fetch('/api/v0/proxy/model-requests'),
      ]);
      if (catR.ok) {
        const c = await catR.json();
        catalog = c.models || [];
        catalogTotal = c.total_active_workers ?? 0;
      }
      if (reqR.ok) requests = (await reqR.json()).requests || [];
      else if (!catR.ok) throw new Error(`models/catalog HTTP ${catR.status}`);
      error = null;
      return true;
    } catch (e) {
      if (!silent) error = (e as Error).message;
      return false;
    } finally {
      if (!silent) loading = false;
    }
  }

  async function submitResolve() {
    if (!resolveModal) return;
    const m = resolveModal;
    resolveModal = null;
    actionLoading = true;
    try {
      const r = await fetch(`/api/v0/proxy/model-requests/${m.requestId}/actions/${m.action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: m.reason }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(JSON.stringify(d));
      }
      await loadAll(true);
    } catch (e) {
      alert(`${m.action} failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  const reqOrder: Record<string, number> = { pending: 0, available: 1, fulfilled: 2, declined: 3 };
  let sortedReqs = $derived(
    [...requests].sort(
      (a, b) =>
        (reqOrder[a.status] ?? 9) - (reqOrder[b.status] ?? 9) ||
        b.created_at.localeCompare(a.created_at),
    ),
  );

  onMount(() => {
    loadAll().then((ok) => (live = ok));
    return autoRefresh({
      refresh: () => loadAll(true),
      setLive: (v) => (live = v),
      types: ['worker.status', 'network.status'],
    });
  });
</script>

<svelte:head>
  <title>Models — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1>
      <a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> models
      {#if !loading}<LiveDot {live} />{/if}
    </h1>
  </header>
  <Nav />

  {#if loading}
    <p class="muted">Loading models…</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else}
    <!-- New-requirement (BYOM demand) queue -->
    <h2 class="section">New-requirement queue</h2>
    <p class="muted">
      Researcher demand for models (BYOM). <strong>pending</strong> = no active worker holds it —
      recruit a volunteer then <em>fulfil</em>, or <em>decline</em>.
    </p>
    {#if requests.length === 0}
      <p class="muted">No model requests yet.</p>
    {:else}
      <table>
        <thead>
          <tr><th>model_id</th><th>tenant</th><th>reason</th><th>status</th><th>created</th><th>resolution</th><th></th></tr>
        </thead>
        <tbody>
          {#each sortedReqs as req (req.request_id)}
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

    <!-- Network model catalog -->
    <h2 class="section">Network model catalog</h2>
    <p class="muted">
      What the fleet can run — the bottom-up aggregate of models active workers hold
      ({catalogTotal} worker{catalogTotal === 1 ? '' : 's'}).
    </p>
    {#if catalog.length === 0}
      <p class="muted">No models available on the network.</p>
    {:else}
      <table>
        <thead><tr><th>model_id</th><th>workers holding it</th></tr></thead>
        <tbody>
          {#each catalog as m (m.model_id)}
            <tr><td class="mono">{m.model_id}</td><td>{m.worker_count}</td></tr>
          {/each}
        </tbody>
      </table>
    {/if}
  {/if}

  {#if resolveModal}
    <div class="modal-backdrop" onclick={() => (resolveModal = null)}></div>
    <div class="modal">
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
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .reason { max-width: 260px; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.status-pending { background: #78350f; color: #fcd34d; }
  .badge.status-available { background: #14532d; color: #86efac; }
  .badge.status-fulfilled { background: #14532d; color: #86efac; }
  .badge.status-declined { background: #7f1d1d; color: #fca5a5; }
  .actions { white-space: nowrap; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.25em 0.65em; border-radius: 4px; cursor: pointer; font: inherit; font-size: 0.85em; }
  button:hover { background: #2a2e3a; }
  button:disabled { opacity: 0.5; cursor: default; }
  button.primary { background: #a78bfa; color: #0a0e1a; border-color: #a78bfa; font-weight: 600; }
  button.danger { background: #7f1d1d; border-color: #7f1d1d; color: #fca5a5; }
  .modal-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); z-index: 10; }
  .modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #1a1e2a; border: 1px solid #2a2e3a; border-radius: 8px; padding: 1.5em; z-index: 11; width: 90%; max-width: 460px; }
  .modal h2 { margin: 0 0 0.5em; color: #fff; font-size: 1.1em; }
  .modal label { display: block; margin: 0.75em 0 0.25em; color: #9ca3af; font-size: 0.9em; }
  .modal textarea { width: 100%; padding: 0.4em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; resize: vertical; }
  .modal-actions { display: flex; gap: 0.75em; justify-content: flex-end; margin-top: 1.25em; }
</style>
