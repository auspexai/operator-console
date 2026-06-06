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

  let requests = $state<ModelRequest[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let actionLoading = $state(false);

  let resolveModal = $state<{
    requestId: string;
    modelId: string;
    action: 'fulfil' | 'decline';
    reason: string;
  } | null>(null);

  async function loadRequests() {
    loading = true;
    error = null;
    try {
      const r = await fetch('/api/v0/proxy/model-requests');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      requests = body.requests || [];
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  async function submitResolve() {
    if (!resolveModal) return;
    actionLoading = true;
    try {
      const r = await fetch(
        `/api/v0/proxy/model-requests/${resolveModal.requestId}/actions/${resolveModal.action}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: resolveModal.reason }),
        }
      );
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        throw new Error(JSON.stringify(detail));
      }
      resolveModal = null;
      await loadRequests();
    } catch (e) {
      alert(`${resolveModal?.action} failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  // pending first (the review queue), then everything else by recency
  const order: Record<string, number> = { pending: 0, available: 1, fulfilled: 2, declined: 3 };
  let sorted = $derived(
    [...requests].sort(
      (a, b) =>
        (order[a.status] ?? 9) - (order[b.status] ?? 9) ||
        b.created_at.localeCompare(a.created_at)
    )
  );
  let pendingCount = $derived(requests.filter((r) => r.status === 'pending').length);

  onMount(loadRequests);
</script>

<svelte:head>
  <title>Model requests — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> model requests</h1>
  </header>
  <Nav />

  <p class="muted">
    Researcher demand for models (BYOM). <strong>pending</strong> = no active worker holds it yet —
    the review queue: recruit a capable volunteer, then <em>fulfil</em>, or <em>decline</em>.
    <strong>available</strong> = the network can already run it.
  </p>

  {#if loading}
    <p class="muted">Loading requests…</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else if requests.length === 0}
    <p class="muted">No model requests yet.</p>
  {:else}
    <p class="muted">{pendingCount} pending · {requests.length} total</p>
    <table>
      <thead>
        <tr>
          <th>model_id</th>
          <th>tenant</th>
          <th>reason</th>
          <th>status</th>
          <th>created</th>
          <th>resolution</th>
          <th>actions</th>
        </tr>
      </thead>
      <tbody>
        {#each sorted as req}
          <tr class:pending={req.status === 'pending'}>
            <td class="mono">
              {req.model_id}
              {#if req.hf_repo}<br /><span class="muted">{req.hf_repo}</span>{/if}
            </td>
            <td class="mono">{req.tenant_id}</td>
            <td class="reason">{req.reason}</td>
            <td><span class="badge status-{req.status}">{req.status}</span></td>
            <td class="mono">{new Date(req.created_at).toLocaleString()}</td>
            <td>
              {#if req.resolved_at}
                <span class="muted">{req.resolved_by ?? '—'}: {req.resolution_reason ?? ''}</span>
              {:else}
                <span class="muted">—</span>
              {/if}
            </td>
            <td class="actions">
              {#if req.status === 'pending'}
                <button
                  class="primary"
                  onclick={() => (resolveModal = { requestId: req.request_id, modelId: req.model_id, action: 'fulfil', reason: '' })}
                  disabled={actionLoading}>fulfil</button>
                <button
                  class="danger"
                  onclick={() => (resolveModal = { requestId: req.request_id, modelId: req.model_id, action: 'decline', reason: '' })}
                  disabled={actionLoading}>decline</button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if resolveModal}
    <div class="modal-backdrop" onclick={() => (resolveModal = null)}></div>
    <div class="tier-modal">
      <h2>{resolveModal.action === 'fulfil' ? 'Fulfil' : 'Decline'} model request</h2>
      <p class="mono">{resolveModal.modelId}</p>
      <p class="muted">
        {resolveModal.action === 'fulfil'
          ? 'Mark resolved — a capable volunteer has been recruited / the model will be supported.'
          : 'Decline this request — the network will not support this model.'}
        The reason is recorded in the audit log.
      </p>
      <label>
        Reason (required)
        <textarea
          bind:value={resolveModal.reason}
          rows="3"
          placeholder={resolveModal.action === 'fulfil'
            ? 'e.g., recruited 2 capable volunteers; model staged'
            : 'e.g., gated model, no volunteer hardware can run it, out of scope'}></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (resolveModal = null)}>cancel</button>
        <button
          class={resolveModal.action === 'fulfil' ? 'primary' : 'danger'}
          onclick={submitResolve}
          disabled={actionLoading || !resolveModal.reason.trim()}>
          {resolveModal.action}
        </button>
      </div>
    </div>
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
  td { padding: 0.5em; border-bottom: 1px solid #1a1e2a; vertical-align: top; }
  tr.pending { background: rgba(120, 90, 10, 0.12); }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .reason { max-width: 280px; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
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
  .tier-modal textarea { width: 100%; padding: 0.4em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; font-size: 0.9em; resize: vertical; }
  .tier-modal textarea:focus { outline: none; border-color: #a78bfa; }
  .modal-actions { display: flex; gap: 0.75em; justify-content: flex-end; margin-top: 1.25em; }
</style>
