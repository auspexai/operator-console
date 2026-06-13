<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import Nav from '$lib/components/Nav.svelte';
  import LiveDot from '$lib/components/LiveDot.svelte';
  import { autoRefresh, type LiveEvent } from '$lib/live';

  type Experiment = {
    experiment_id: string;
    tenant_id: string;
    status: string;
    integrity_policy: string;
    submitted_at: string;
    last_action_at: string | null;
    started_at: string | null;
    completed_at: string | null;
    submissions_finalized: boolean;
    max_unit_duration_seconds: number | null;
    max_units: number | null;
    max_concurrent_assignments: number | null;
    max_payload_bytes: number | null;
    // §9 #48 admission-assessment provenance.
    research_class: string | null;
    assessment_decision: string | null;
    assessment_tier: number | null;
    assessment_rationale: string | null;
    assessment_envelope: { name: string; passed: boolean; detail: string }[] | null;
    assessed_by: string | null;
    // M-Results retention (O-M8). TTLs + projection are OPERATOR_ONLY.
    retention_hold: boolean | null;
    retention_hold_reason: string | null;
    results_collected_at: string | null;
    raw_payload_ttl_days: number | null;
    consensus_ttl_days: number | null;
    raw_payload_age_off_at: string | null;
  };

  type WorkUnitsResponse = {
    work_units: any[];
    counts_by_status: Record<string, number>;
  };

  // page.params.id is `string | undefined` in the SvelteKit types but always
  // present for this [id] route at runtime; coalesce so it types as string.
  let experimentId = $derived(page.params.id ?? '');
  let experiment = $state<Experiment | null>(null);
  let workUnits = $state<WorkUnitsResponse | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let actionLoading = $state(false);
  let live = $state(false);

  let approvalForm = $state<{
    integrity_policy: string;
    max_unit_duration_seconds: string;
    max_units: string;
    max_concurrent_assignments: string;
    max_payload_bytes: string;
  } | null>(null);

  const statusBadge: Record<string, string> = {
    submitted: 'pending-badge',
    approved: 'ok',
    paused: 'paused-badge',
    completed: 'completed-badge',
    aborted: 'aborted-badge',
    archived: 'archived-badge',
  };

  async function loadExperiment(silent = false): Promise<boolean> {
    if (!silent) loading = true;
    try {
      const [expRes, wuRes] = await Promise.all([
        fetch(`/api/v0/proxy/experiments/${encodeURIComponent(experimentId)}`),
        fetch(`/api/v0/proxy/experiments/${encodeURIComponent(experimentId)}/work-units`),
      ]);
      if (!expRes.ok) throw new Error(`Experiment: HTTP ${expRes.status}`);
      experiment = await expRes.json();
      if (wuRes.ok) {
        workUnits = await wuRes.json();
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

  function showApprovalForm() {
    approvalForm = {
      integrity_policy: 'standard',
      max_unit_duration_seconds: '1800',
      max_units: '500',
      max_concurrent_assignments: '10',
      max_payload_bytes: '1048576',
    };
  }

  async function submitApproval() {
    if (!approvalForm) return;
    actionLoading = true;
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

      const r = await fetch(`/api/v0/proxy/experiments/${encodeURIComponent(experimentId)}/actions/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const detail = await r.json();
        throw new Error(JSON.stringify(detail));
      }
      approvalForm = null;
      await loadExperiment();
    } catch (e) {
      alert(`Approval failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  async function experimentAction(action: string) {
    if (action === 'abort' && !confirm(`Abort experiment ${experimentId}?`)) return;
    actionLoading = true;
    try {
      const r = await fetch(`/api/v0/proxy/experiments/${encodeURIComponent(experimentId)}/actions/${action}`, {
        method: 'POST',
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await loadExperiment();
    } catch (e) {
      alert(`${action} failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  // Set integrity policy + trigger pre-stage (I2: moved here from the dissolved
  // /scheduler — these are experiment-scoped actions, so the experiment record
  // is their canonical home). Both mandatory-reason + audited.
  let policyModal = $state<{ policy: string; reason: string } | null>(null);
  let prestageModal = $state<{ reason: string } | null>(null);

  async function reasonedAction(action: string, body: Record<string, unknown>, label: string) {
    actionLoading = true;
    try {
      const r = await fetch(
        `/api/v0/proxy/experiments/${encodeURIComponent(experimentId)}/actions/${action}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      );
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(JSON.stringify(d));
      }
      await loadExperiment();
    } catch (e) {
      alert(`${label} failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  async function submitPolicy() {
    if (!policyModal || !policyModal.reason.trim()) return;
    const m = policyModal;
    policyModal = null;
    await reasonedAction(
      'set-integrity-policy',
      { integrity_policy: m.policy, reason: m.reason },
      'set policy',
    );
  }

  async function submitPrestage() {
    if (!prestageModal || !prestageModal.reason.trim()) return;
    const m = prestageModal;
    prestageModal = null;
    await reasonedAction('trigger-prestage', { reason: m.reason }, 'pre-stage');
  }

  // Retention hold / release (O-M8). Mirrors the account suspend/unsuspend
  // pattern: mandatory reason on hold, confirm-gated release, silent refetch.
  let holdModal = $state<{ reason: string } | null>(null);

  async function submitHold() {
    if (!holdModal || !holdModal.reason.trim()) return;
    actionLoading = true;
    try {
      const r = await fetch(
        `/api/v0/proxy/experiments/${encodeURIComponent(experimentId)}/actions/retention-hold`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: holdModal.reason }),
        }
      );
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        throw new Error(JSON.stringify(detail));
      }
      holdModal = null;
      await loadExperiment();
    } catch (e) {
      alert(`Place hold failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  async function releaseHold() {
    if (!confirm(`Release the retention hold on ${experimentId}? Age-off resumes per the normal schedule.`))
      return;
    actionLoading = true;
    try {
      const r = await fetch(
        `/api/v0/proxy/experiments/${encodeURIComponent(experimentId)}/actions/release-hold`,
        { method: 'POST' }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await loadExperiment();
    } catch (e) {
      alert(`Release hold failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  }

  let totalUnits = $derived(
    workUnits?.counts_by_status
      ? Object.values(workUnits.counts_by_status).reduce((a, b) => a + b, 0)
      : 0
  );
  let completedUnits = $derived(workUnits?.counts_by_status?.completed ?? 0);
  let progressPct = $derived(totalUnits > 0 ? Math.round((completedUnits / totalUnits) * 100) : 0);

  onMount(() => {
    loadExperiment().then((ok) => (live = ok));
    // Poll is the truth, the SSE doorbell is a hint. Scope the doorbell to THIS
    // experiment's frames (the firehose carries every experiment) so progress +
    // lifecycle update live without re-snapshotting on unrelated traffic.
    return autoRefresh({
      refresh: () => loadExperiment(true),
      setLive: (v) => (live = v),
      types: ['experiment.status', 'unit.progress', 'receipt.issued'],
      eventFilter: (ev: LiveEvent) =>
        (ev.data as { experiment_id?: string } | null)?.experiment_id === experimentId,
    });
  });
</script>

<svelte:head>
  <title>Experiment {experimentId} — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> experiment detail
      {#if !loading}<LiveDot {live} />{/if}
    </h1>
  </header>
  <Nav />

  <p class="breadcrumb"><a href="/experiments">experiments</a> / <span class="mono">{experimentId}</span></p>

  {#if loading}
    <p class="muted">Loading experiment…</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else if experiment}
    <section class="card">
      <h2>Metadata</h2>
      <dl>
        <dt>experiment_id</dt><dd class="mono">{experiment.experiment_id}</dd>
        <dt>tenant</dt><dd class="mono">{experiment.tenant_id}</dd>
        <dt>status</dt>
        <dd><span class="badge {statusBadge[experiment.status] ?? ''}">{experiment.status}</span></dd>
        <dt>integrity policy</dt><dd>{experiment.integrity_policy ?? 'standard'}</dd>
        <dt>submitted</dt><dd class="mono">{new Date(experiment.submitted_at).toLocaleString()}</dd>
        {#if experiment.last_action_at}
          <dt>last action</dt><dd class="mono">{new Date(experiment.last_action_at).toLocaleString()}</dd>
        {/if}
        {#if experiment.started_at}
          <dt>started</dt><dd class="mono">{new Date(experiment.started_at).toLocaleString()}</dd>
        {/if}
        {#if experiment.completed_at}
          <dt>completed</dt><dd class="mono">{new Date(experiment.completed_at).toLocaleString()}</dd>
        {/if}
        <dt>submissions finalized</dt><dd>{experiment.submissions_finalized ? 'yes' : 'no'}</dd>
      </dl>
    </section>

    {#if experiment.assessment_decision}
      <section class="card">
        <h2>Assessment <span class="muted small">§9 #48</span></h2>
        <dl>
          <dt>decision</dt>
          <dd><span class="badge assess-{experiment.assessment_decision}">{experiment.assessment_decision}</span></dd>
          {#if experiment.research_class}<dt>research class</dt><dd class="mono">{experiment.research_class}</dd>{/if}
          {#if experiment.assessment_tier != null}<dt>tenant tier</dt><dd>T{experiment.assessment_tier}</dd>{/if}
          {#if experiment.assessment_rationale}<dt>rationale</dt><dd>{experiment.assessment_rationale}</dd>{/if}
          {#if experiment.assessed_by}<dt>assessed by</dt><dd class="mono">{experiment.assessed_by}</dd>{/if}
        </dl>
        {#if experiment.assessment_envelope?.length}
          <table class="envelope">
            <tbody>
              {#each experiment.assessment_envelope as c}
                <tr>
                  <td>{c.passed ? '✓' : '✗'}</td>
                  <td class="mono">{c.name}</td>
                  <td class="muted small">{c.detail}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </section>
    {/if}

    {#if experiment.max_unit_duration_seconds || experiment.max_units || experiment.max_concurrent_assignments || experiment.max_payload_bytes}
      <section class="card">
        <h2>Resource bounds</h2>
        <dl>
          {#if experiment.max_unit_duration_seconds != null}
            <dt>max unit duration</dt><dd>{experiment.max_unit_duration_seconds}s</dd>
          {/if}
          {#if experiment.max_units != null}
            <dt>max units</dt><dd>{experiment.max_units}</dd>
          {/if}
          {#if experiment.max_concurrent_assignments != null}
            <dt>max concurrent</dt><dd>{experiment.max_concurrent_assignments}</dd>
          {/if}
          {#if experiment.max_payload_bytes != null}
            <dt>max payload</dt><dd>{formatBytes(experiment.max_payload_bytes)}</dd>
          {/if}
        </dl>
      </section>
    {/if}

    <section class="card">
      <h2>Retention</h2>
      <dl>
        <dt>raw payload TTL</dt>
        <dd>{experiment.raw_payload_ttl_days != null ? `${experiment.raw_payload_ttl_days} days` : '30 days (default)'}</dd>
        <dt>consensus TTL</dt>
        <dd>{experiment.consensus_ttl_days != null ? `${experiment.consensus_ttl_days} days` : 'experiment-lifetime (default)'}</dd>
        <dt>results collected</dt>
        <dd class="mono">{experiment.results_collected_at ? new Date(experiment.results_collected_at).toLocaleString() : '— not yet collected'}</dd>
        <dt>raw age-off projected</dt>
        <dd class="mono">
          {#if experiment.raw_payload_age_off_at}
            {new Date(experiment.raw_payload_age_off_at).toLocaleString()}
          {:else}
            <span class="muted">— anchored on collection</span>
          {/if}
        </dd>
        <dt>retention hold</dt>
        <dd>
          {#if experiment.retention_hold}
            <span class="badge held-badge">on hold</span>
            {#if experiment.retention_hold_reason}
              <div class="muted reason">reason: {experiment.retention_hold_reason}</div>
            {/if}
          {:else}
            <span class="muted">none — age-off active</span>
          {/if}
        </dd>
      </dl>
      <div class="action-row" style="margin-top: 0.75em;">
        {#if experiment.retention_hold}
          <button onclick={releaseHold} disabled={actionLoading}>release hold</button>
        {:else}
          <button onclick={() => (holdModal = { reason: '' })} disabled={actionLoading}>place retention hold…</button>
        {/if}
      </div>
    </section>

    {#if workUnits}
      <section class="card">
        <h2>Work-unit progress</h2>
        <div class="progress-bar-container">
          <div class="progress-bar" style="width: {progressPct}%"></div>
        </div>
        <p class="progress-text">{completedUnits} / {totalUnits} completed ({progressPct}%)</p>
        {#if Object.keys(workUnits.counts_by_status).length}
          <div class="status-counts">
            {#each Object.entries(workUnits.counts_by_status) as [status, count]}
              <span class="status-count">
                <span class="badge {statusBadge[status] ?? ''}">{status}</span>
                <span>{count}</span>
              </span>
            {/each}
          </div>
        {/if}
      </section>
    {/if}

    <section class="card">
      <h2>Actions</h2>
      <div class="action-row">
        {#if experiment.status === 'submitted'}
          <button class="primary" onclick={showApprovalForm} disabled={actionLoading}>approve</button>
        {/if}
        {#if experiment.status === 'approved'}
          <button onclick={() => experimentAction('pause')} disabled={actionLoading}>pause</button>
          <button class="danger" onclick={() => experimentAction('abort')} disabled={actionLoading}>abort</button>
        {/if}
        {#if experiment.status === 'paused'}
          <button onclick={() => experimentAction('resume')} disabled={actionLoading}>resume</button>
          <button class="danger" onclick={() => experimentAction('abort')} disabled={actionLoading}>abort</button>
        {/if}
        {#if experiment.status === 'approved' || experiment.status === 'paused'}
          <button onclick={() => (policyModal = { policy: experiment?.integrity_policy ?? 'standard', reason: '' })} disabled={actionLoading}>set integrity policy…</button>
          <button onclick={() => (prestageModal = { reason: '' })} disabled={actionLoading}>trigger pre-stage…</button>
        {/if}
        {#if !['submitted', 'approved', 'paused'].includes(experiment.status)}
          <span class="muted">No actions available for {experiment.status} experiments.</span>
        {/if}
      </div>
    </section>
  {/if}

  {#if approvalForm}
    <div class="modal-backdrop" onclick={() => (approvalForm = null)}></div>
    <div class="approval-modal">
      <h2>Approve experiment</h2>
      <p class="mono">{experimentId}</p>

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

  {#if policyModal}
    <div class="modal-backdrop" onclick={() => (policyModal = null)}></div>
    <div class="approval-modal">
      <h2>Set integrity policy</h2>
      <p class="mono">{experimentId}</p>
      <p class="warning">Affects FUTURE units only — units already submitted keep their replication target.</p>
      <label>
        Policy
        <select bind:value={policyModal.policy}>
          <option value="standard">standard (replication 3)</option>
          <option value="high">high (replication 5)</option>
          <option value="trusted">trusted (replication 1; T2+ only)</option>
        </select>
      </label>
      <label>
        Reason (required)
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
    <div class="approval-modal">
      <h2>Trigger pre-stage</h2>
      <p class="mono">{experimentId}</p>
      <p class="muted">Eagerly pulls this experiment's required model(s) onto eligible auto-acquire workers now (bounded by the replication need), so its units aren't bottlenecked on first-assignment pulls.</p>
      <label>
        Reason (required)
        <textarea bind:value={prestageModal.reason} rows="3" placeholder="recorded in the audit log"></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (prestageModal = null)}>cancel</button>
        <button class="primary" onclick={submitPrestage} disabled={actionLoading || !prestageModal.reason.trim()}>pre-stage</button>
      </div>
    </div>
  {/if}

  {#if holdModal}
    <div class="modal-backdrop" onclick={() => (holdModal = null)}></div>
    <div class="approval-modal">
      <h2>Place retention hold</h2>
      <p class="mono">{experimentId}</p>
      <p class="warning">
        A hold pauses age-off for this experiment's payloads until released — use
        only for audit/legal retention. The reason is recorded in the audit log.
      </p>
      <label>
        Reason (required)
        <textarea
          bind:value={holdModal.reason}
          rows="3"
          placeholder="Why must this experiment's data be retained? (e.g., litigation hold, regulatory inquiry, integrity investigation)"
        ></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (holdModal = null)}>cancel</button>
        <button class="primary" onclick={submitHold} disabled={actionLoading || !holdModal.reason.trim()}>
          place hold
        </button>
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
  .breadcrumb a:hover { text-decoration: underline; }
  .card { background: #11152b; border: 1px solid #1e2340; border-radius: 12px; padding: 1em 1.25em; margin: 1em 0; }
  .card h2 { margin-top: 0; }
  dl { display: grid; grid-template-columns: 14em 1fr; gap: 0.3em 1em; }
  dt { color: #9ca3af; }
  dd { margin: 0; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; word-break: break-all; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.ok { background: #14532d; color: #86efac; }
  .badge.assess-auto { background: #14532d; color: #86efac; }
  .badge.assess-review { background: #854d0e; color: #fde68a; }
  .small { font-size: 0.82em; }
  table.envelope { width: 100%; border-collapse: collapse; margin-top: 0.5em; font-size: 0.85em; }
  table.envelope td { padding: 0.2em 0.5em; border-bottom: 1px solid #1a1e2a; vertical-align: top; }
  table.envelope td:first-child { width: 1.4em; }
  .pending-badge { background: #854d0e; color: #fde68a; }
  .paused-badge { background: #1e3a5f; color: #93c5fd; }
  .completed-badge { background: #14532d; color: #86efac; }
  .aborted-badge { background: #7f1d1d; color: #fca5a5; }
  .archived-badge { background: #374151; color: #6b7280; }
  .held-badge { background: #854d0e; color: #fde68a; }
  .reason { margin-top: 0.25em; font-size: 0.85em; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  .progress-bar-container { background: #1f2937; border-radius: 4px; height: 0.75em; overflow: hidden; margin: 0.5em 0; }
  .progress-bar { background: #a78bfa; height: 100%; border-radius: 4px; transition: width 0.3s ease; min-width: 0; }
  .progress-text { color: #9ca3af; font-size: 0.85em; margin: 0.25em 0 0.5em; }
  .status-counts { display: flex; gap: 1em; flex-wrap: wrap; }
  .status-count { display: flex; align-items: center; gap: 0.35em; font-size: 0.9em; color: #d4d4dc; }
  .action-row { display: flex; gap: 0.5em; flex-wrap: wrap; align-items: center; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.35em 0.75em; border-radius: 4px; cursor: pointer; font: inherit; font-size: 0.85em; }
  button:hover { background: #2a2e3a; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  button.primary { background: #a78bfa; color: #0a0e1a; border-color: #a78bfa; font-weight: 600; }
  button.primary:hover { background: #c4b5fd; }
  button.danger { background: #7f1d1d; border-color: #7f1d1d; color: #fca5a5; }
  button.danger:hover { background: #991b1b; }
  .modal-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); z-index: 10; }
  .approval-modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #1a1e2a; border: 1px solid #2a2e3a; border-radius: 8px; padding: 1.5em; z-index: 11; width: 90%; max-width: 500px; }
  .approval-modal h2 { margin: 0 0 0.5em; color: #fff; font-size: 1.1em; }
  .approval-modal label { display: block; margin: 0.75em 0 0.25em; color: #9ca3af; font-size: 0.9em; }
  .approval-modal select, .approval-modal input, .approval-modal textarea { width: 100%; padding: 0.4em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; resize: vertical; }
  .warning { background: #422006; border: 1px solid #854d0e; color: #fde68a; border-radius: 6px; padding: 0.6em 0.8em; font-size: 0.85em; margin: 0.75em 0 0; }
  .modal-actions { display: flex; gap: 0.75em; justify-content: flex-end; margin-top: 1.25em; }
</style>
