<script lang="ts">
  import { onMount } from 'svelte';

  type Experiment = {
    experiment_id: string;
    tenant_id: string;
    status: string;
    integrity_policy: string;
    submitted_at: string;
    started_at: string | null;
    completed_at: string | null;
    submissions_finalized: boolean;
    max_unit_duration_seconds: number | null;
    max_units: number | null;
    max_concurrent_assignments: number | null;
    max_payload_bytes: number | null;
  };

  let experiments = $state<Experiment[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let approvalForm = $state<{
    experimentId: string;
    integrity_policy: string;
    max_unit_duration_seconds: string;
    max_units: string;
    max_concurrent_assignments: string;
    max_payload_bytes: string;
  } | null>(null);

  async function loadExperiments() {
    loading = true;
    error = null;
    try {
      const r = await fetch('/api/v0/proxy/experiments');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      experiments = body.experiments || body || [];
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  function showApprovalForm(exp: Experiment) {
    approvalForm = {
      experimentId: exp.experiment_id,
      integrity_policy: 'standard',
      max_unit_duration_seconds: '1800',
      max_units: '500',
      max_concurrent_assignments: '10',
      max_payload_bytes: '1048576',
    };
  }

  async function submitApproval() {
    if (!approvalForm) return;
    try {
      const body: Record<string, any> = {
        integrity_policy: approvalForm.integrity_policy,
      };
      if (approvalForm.max_unit_duration_seconds)
        body.max_unit_duration_seconds = parseInt(approvalForm.max_unit_duration_seconds);
      if (approvalForm.max_units)
        body.max_units = parseInt(approvalForm.max_units);
      if (approvalForm.max_concurrent_assignments)
        body.max_concurrent_assignments = parseInt(approvalForm.max_concurrent_assignments);
      if (approvalForm.max_payload_bytes)
        body.max_payload_bytes = parseInt(approvalForm.max_payload_bytes);

      const r = await fetch(`/api/v0/proxy/experiments/${approvalForm.experimentId}/actions/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const detail = await r.json();
        throw new Error(JSON.stringify(detail));
      }
      approvalForm = null;
      await loadExperiments();
    } catch (e) {
      alert(`Approval failed: ${(e as Error).message}`);
    }
  }

  const statusBadge: Record<string, string> = {
    submitted: 'pending-badge',
    approved: 'ok',
    paused: 'paused-badge',
    completed: 'completed-badge',
    aborted: 'aborted-badge',
    archived: 'archived-badge',
  };

  onMount(loadExperiments);
</script>

<svelte:head>
  <title>Experiments — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> experiments</h1>
  </header>

  {#if loading}
    <p class="muted">Loading experiments…</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else if experiments.length === 0}
    <p class="muted">No experiments submitted.</p>
  {:else}
    <table>
      <thead>
        <tr>
          <th>experiment_id</th>
          <th>tenant</th>
          <th>status</th>
          <th>integrity</th>
          <th>submitted</th>
          <th>actions</th>
        </tr>
      </thead>
      <tbody>
        {#each experiments as exp}
          <tr>
            <td class="mono">{exp.experiment_id}</td>
            <td class="mono">{exp.tenant_id}</td>
            <td><span class="badge {statusBadge[exp.status] ?? ''}">{exp.status}</span></td>
            <td>{exp.integrity_policy ?? 'standard'}</td>
            <td class="mono">{new Date(exp.submitted_at).toLocaleDateString()}</td>
            <td>
              {#if exp.status === 'submitted'}
                <button class="primary" onclick={() => showApprovalForm(exp)}>approve</button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p class="muted">{experiments.length} experiment(s)</p>
  {/if}

  {#if approvalForm}
    <div class="modal-backdrop" onclick={() => (approvalForm = null)}></div>
    <div class="approval-modal">
      <h2>Approve experiment</h2>
      <p class="mono">{approvalForm.experimentId}</p>

      <label>
        Integrity policy
        <select bind:value={approvalForm.integrity_policy}>
          <option value="standard">standard (N=3, all tiers)</option>
          <option value="high">high (N=5, higher confidence)</option>
          <option value="trusted">trusted (N=1, T2+ only)</option>
        </select>
      </label>

      <label>
        Max unit duration (seconds)
        <input type="number" bind:value={approvalForm.max_unit_duration_seconds} />
      </label>

      <label>
        Max total units
        <input type="number" bind:value={approvalForm.max_units} />
      </label>

      <label>
        Max concurrent assignments
        <input type="number" bind:value={approvalForm.max_concurrent_assignments} />
      </label>

      <label>
        Max payload bytes
        <input type="number" bind:value={approvalForm.max_payload_bytes} />
      </label>

      <div class="modal-actions">
        <button onclick={() => (approvalForm = null)}>cancel</button>
        <button class="primary" onclick={submitApproval}>approve with these settings</button>
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
  td { padding: 0.5em; border-bottom: 1px solid #1a1e2a; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.ok { background: #14532d; color: #86efac; }
  .pending-badge { background: #854d0e; color: #fde68a; }
  .paused-badge { background: #1e3a5f; color: #93c5fd; }
  .completed-badge { background: #14532d; color: #86efac; }
  .aborted-badge { background: #7f1d1d; color: #fca5a5; }
  .archived-badge { background: #374151; color: #6b7280; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.25em 0.65em; border-radius: 4px; cursor: pointer; font: inherit; font-size: 0.85em; }
  button:hover { background: #2a2e3a; }
  button.primary { background: #a78bfa; color: #0a0e1a; border-color: #a78bfa; font-weight: 600; }
  button.primary:hover { background: #c4b5fd; }
  .modal-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); z-index: 10; }
  .approval-modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #1a1e2a; border: 1px solid #2a2e3a; border-radius: 8px; padding: 1.5em; z-index: 11; width: 90%; max-width: 500px; }
  .approval-modal h2 { margin: 0 0 0.5em; color: #fff; font-size: 1.1em; }
  .approval-modal label { display: block; margin: 0.75em 0 0.25em; color: #9ca3af; font-size: 0.9em; }
  .approval-modal select, .approval-modal input { width: 100%; padding: 0.4em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; }
  .modal-actions { display: flex; gap: 0.75em; justify-content: flex-end; margin-top: 1.25em; }
</style>
