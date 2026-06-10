<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';
  import { autoRefresh } from '$lib/live';
  import LiveDot from '$lib/components/LiveDot.svelte';

  // §9 #46: the code-plane requirements queue — software requests with their
  // dependencies/security/alternatives assessment stage, the audited
  // approve/decline (warn-but-allow gates on unassessed/auto-draft approvals),
  // and the release registry that fulfils approved requests + announces to
  // the fleet via the worker heartbeat.

  type Assessment = {
    dependencies: string;
    security: string;
    alternatives: string;
    summary: string | null;
  };

  type SoftwareRequest = {
    request_id: string;
    tenant_id: string;
    title: string;
    description: string;
    reason: string;
    status: string; // pending | assessed | approved | declined | released
    created_at: string;
    assessment: Assessment | null;
    assessment_draft: boolean;
    assessed_at: string | null;
    assessed_by: string | null;
    resolved_at: string | null;
    resolved_by: string | null;
    resolution_reason: string | null;
    release_version: string | null;
  };

  type Release = {
    version: string;
    channel: string;
    headline: string;
    notes: string | null;
    release_url: string | null;
    published_at: string;
    announced_by: string;
  };

  let requests = $state<SoftwareRequest[]>([]);
  let releases = $state<Release[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let actionLoading = $state(false);
  let live = $state(false);

  let assessModal = $state<{
    requestId: string;
    title: string;
    ratifying: boolean; // pre-filled from an existing draft
    dependencies: string;
    security: string;
    alternatives: string;
    summary: string;
  } | null>(null);

  let resolveModal = $state<{
    requestId: string;
    title: string;
    action: 'approve' | 'decline';
    warning: string | null; // gate warn-text shown inside the modal
    reason: string;
  } | null>(null);

  let releaseModal = $state<{
    version: string;
    headline: string;
    notes: string;
    releaseUrl: string;
    fulfils: Record<string, boolean>;
  } | null>(null);

  async function loadAll(silent = false): Promise<boolean> {
    if (!silent) loading = true;
    try {
      const [reqR, relR] = await Promise.all([
        fetch('/api/v0/proxy/software-requests'),
        fetch('/api/v0/proxy/releases'),
      ]);
      if (!reqR.ok) throw new Error(`software-requests HTTP ${reqR.status}`);
      requests = (await reqR.json()).requests || [];
      if (relR.ok) releases = (await relR.json()).releases || [];
      error = null;
      return true;
    } catch (e) {
      if (!silent) error = (e as Error).message;
      return false;
    } finally {
      if (!silent) loading = false;
    }
  }

  function openAssess(req: SoftwareRequest) {
    assessModal = {
      requestId: req.request_id,
      title: req.title,
      ratifying: req.assessment_draft && req.assessment != null,
      dependencies: req.assessment?.dependencies ?? '',
      security: req.assessment?.security ?? '',
      alternatives: req.assessment?.alternatives ?? '',
      summary: req.assessment?.summary ?? '',
    };
  }

  async function submitAssess() {
    if (!assessModal) return;
    const m = assessModal;
    assessModal = null;
    actionLoading = true;
    try {
      const r = await fetch(`/api/v0/proxy/software-requests/${m.requestId}/actions/assess`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          assessment: {
            dependencies: m.dependencies,
            security: m.security,
            alternatives: m.alternatives,
            summary: m.summary.trim() ? m.summary : null,
          },
          draft: false, // a human attaching/ratifying via the console is never a draft
        }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(JSON.stringify(d));
      }
      await loadAll(true);
    } catch (e) {
      alert(`assess failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  function openResolve(req: SoftwareRequest, action: 'approve' | 'decline') {
    let warning: string | null = null;
    if (action === 'approve') {
      if (req.assessment == null) {
        warning =
          'No assessment attached — approving anyway is recorded as a gate override in the audit log.';
      } else if (req.assessment_draft) {
        warning =
          'The assessment is an unreviewed AUTO-DRAFT — ratify it first to clear this warning; approving now records a gate override.';
      }
    }
    resolveModal = { requestId: req.request_id, title: req.title, action, warning, reason: '' };
  }

  async function submitResolve() {
    if (!resolveModal) return;
    const m = resolveModal;
    resolveModal = null;
    actionLoading = true;
    try {
      const r = await fetch(`/api/v0/proxy/software-requests/${m.requestId}/actions/${m.action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: m.reason }),
      });
      const result = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(JSON.stringify(result));
      if (result.gate_override && result.gate_warnings?.length) {
        alert(
          `Approved with gate override:\n\n${result.gate_warnings.map((w: string) => `• ${w}`).join('\n')}\n\nThis override is recorded in the audit log.`,
        );
      }
      await loadAll(true);
    } catch (e) {
      alert(`${m.action} failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  function openRelease() {
    const fulfils: Record<string, boolean> = {};
    for (const r of requests) if (r.status === 'approved') fulfils[r.request_id] = false;
    releaseModal = { version: '', headline: '', notes: '', releaseUrl: '', fulfils };
  }

  async function submitRelease() {
    if (!releaseModal) return;
    const m = releaseModal;
    releaseModal = null;
    actionLoading = true;
    try {
      const r = await fetch('/api/v0/proxy/releases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          version: m.version.trim().replace(/^v/, ''),
          headline: m.headline,
          notes: m.notes.trim() ? m.notes : null,
          release_url: m.releaseUrl.trim() ? m.releaseUrl : null,
          fulfils_request_ids: Object.entries(m.fulfils)
            .filter(([, v]) => v)
            .map(([k]) => k),
        }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(JSON.stringify(d));
      }
      await loadAll(true);
    } catch (e) {
      alert(`record release failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  const reqOrder: Record<string, number> = {
    pending: 0,
    assessed: 1,
    approved: 2,
    released: 3,
    declined: 4,
  };
  let sortedReqs = $derived(
    [...requests].sort(
      (a, b) =>
        (reqOrder[a.status] ?? 9) - (reqOrder[b.status] ?? 9) ||
        b.created_at.localeCompare(a.created_at),
    ),
  );
  let approvedCount = $derived(requests.filter((r) => r.status === 'approved').length);

  onMount(() => {
    loadAll().then((ok) => (live = ok));
    return autoRefresh({
      refresh: () => loadAll(true),
      setLive: (v) => (live = v),
      types: [
        'requirement.submitted',
        'requirement.assessed',
        'requirement.resolved',
        'release.published',
      ],
    });
  });
</script>

<svelte:head>
  <title>Requests — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1>
      <a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> requests
      {#if !loading}<LiveDot {live} />{/if}
    </h1>
  </header>
  <Nav />

  {#if loading}
    <p class="muted">Loading requests…</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else}
    <!-- Software-requirements queue -->
    <h2 class="section">Software-requirements queue</h2>
    <p class="muted">
      Code-plane demand: capabilities the worker baseline doesn't provide. Review the
      dependencies/security/alternatives assessment, then <em>approve</em> or <em>decline</em>
      (mandatory reason). Approving without a ratified assessment records a gate override.
    </p>
    {#if requests.length === 0}
      <p class="muted">No software requests yet.</p>
    {:else}
      <table>
        <thead>
          <tr><th>title</th><th>tenant</th><th>status</th><th>assessment</th><th>created</th><th>resolution</th><th></th></tr>
        </thead>
        <tbody>
          {#each sortedReqs as req (req.request_id)}
            <tr class:pending={req.status === 'pending' || req.status === 'assessed'}>
              <td>
                <strong>{req.title}</strong>
                <details>
                  <summary class="muted">details</summary>
                  <p class="detail-text">{req.description}</p>
                  <p class="detail-text muted">why: {req.reason}</p>
                </details>
              </td>
              <td class="mono">{req.tenant_id}</td>
              <td>
                <span class="badge status-{req.status}">{req.status}</span>
                {#if req.release_version}<br /><span class="muted mono">v{req.release_version}</span>{/if}
              </td>
              <td class="assessment-cell">
                {#if req.assessment}
                  {#if req.assessment_draft}
                    <span class="badge draft">AUTO-DRAFT — unreviewed</span>
                  {:else}
                    <span class="badge ratified">ratified{#if req.assessed_by}&nbsp;· {req.assessed_by}{/if}</span>
                  {/if}
                  <details>
                    <summary class="muted">view assessment</summary>
                    <dl>
                      <dt>dependencies</dt><dd>{req.assessment.dependencies}</dd>
                      <dt>security</dt><dd>{req.assessment.security}</dd>
                      <dt>alternatives</dt><dd>{req.assessment.alternatives}</dd>
                      {#if req.assessment.summary}<dt>summary</dt><dd>{req.assessment.summary}</dd>{/if}
                    </dl>
                  </details>
                {:else}
                  <span class="warn-text">no assessment attached</span>
                {/if}
              </td>
              <td class="mono">{new Date(req.created_at).toLocaleString()}</td>
              <td>{#if req.resolved_at}<span class="muted">{req.resolved_by ?? '—'}: {req.resolution_reason ?? ''}</span>{:else}<span class="muted">—</span>{/if}</td>
              <td class="actions">
                {#if req.status === 'pending' || req.status === 'assessed'}
                  <button onclick={() => openAssess(req)} disabled={actionLoading}>
                    {req.assessment_draft ? 'review draft' : req.assessment ? 're-assess' : 'assess'}
                  </button>
                  <button class="primary" onclick={() => openResolve(req, 'approve')} disabled={actionLoading}>approve</button>
                  <button class="danger" onclick={() => openResolve(req, 'decline')} disabled={actionLoading}>decline</button>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}

    <!-- Release registry -->
    <h2 class="section">Releases</h2>
    <p class="muted">
      Recording a release announces it to the fleet (worker heartbeat) and fulfils the approved
      requests it ships. Volunteers elect to upgrade — never automatic.
      <button class="primary inline" onclick={openRelease} disabled={actionLoading}>record release…</button>
      {#if approvedCount > 0}<span class="warn-text">{approvedCount} approved request{approvedCount === 1 ? '' : 's'} awaiting a release</span>{/if}
    </p>
    {#if releases.length === 0}
      <p class="muted">No releases recorded yet.</p>
    {:else}
      <table>
        <thead><tr><th>version</th><th>channel</th><th>headline</th><th>announced</th><th>by</th><th></th></tr></thead>
        <tbody>
          {#each releases as rel (rel.channel + rel.version)}
            <tr>
              <td class="mono">v{rel.version}</td>
              <td class="mono">{rel.channel}</td>
              <td>{rel.headline}</td>
              <td class="mono">{new Date(rel.published_at).toLocaleString()}</td>
              <td class="mono">{rel.announced_by}</td>
              <td>{#if rel.release_url}<a href={rel.release_url} target="_blank" rel="noreferrer">release ↗</a>{/if}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  {/if}

  {#if assessModal}
    <div class="modal-backdrop" onclick={() => (assessModal = null)}></div>
    <div class="modal wide">
      <h2>{assessModal.ratifying ? 'Review & ratify assessment' : 'Attach assessment'}</h2>
      <p class="mono">{assessModal.title}</p>
      {#if assessModal.ratifying}
        <p class="warn-text">
          Pre-filled from the agent's auto-draft — review and edit before saving; saving ratifies it.
        </p>
      {/if}
      <label>Dependencies — what does this pull in?
        <textarea bind:value={assessModal.dependencies} rows="3"></textarea>
      </label>
      <label>Security — attack surface / trust impact
        <textarea bind:value={assessModal.security} rows="3"></textarea>
      </label>
      <label>Alternatives — other ways to meet the need
        <textarea bind:value={assessModal.alternatives} rows="3"></textarea>
      </label>
      <label>Summary (optional)
        <textarea bind:value={assessModal.summary} rows="2"></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (assessModal = null)}>cancel</button>
        <button
          class="primary"
          onclick={submitAssess}
          disabled={actionLoading ||
            !assessModal.dependencies.trim() ||
            !assessModal.security.trim() ||
            !assessModal.alternatives.trim()}>{assessModal.ratifying ? 'ratify' : 'attach'}</button>
      </div>
    </div>
  {/if}

  {#if resolveModal}
    <div class="modal-backdrop" onclick={() => (resolveModal = null)}></div>
    <div class="modal">
      <h2>{resolveModal.action === 'approve' ? 'Approve' : 'Decline'} software request</h2>
      <p class="mono">{resolveModal.title}</p>
      {#if resolveModal.warning}
        <p class="warn-text">{resolveModal.warning}</p>
      {/if}
      <label>Reason (required)
        <textarea bind:value={resolveModal.reason} rows="3" placeholder="recorded in the audit log"></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (resolveModal = null)}>cancel</button>
        <button class={resolveModal.action === 'approve' ? 'primary' : 'danger'} onclick={submitResolve} disabled={actionLoading || !resolveModal.reason.trim()}>{resolveModal.action}</button>
      </div>
    </div>
  {/if}

  {#if releaseModal}
    <div class="modal-backdrop" onclick={() => (releaseModal = null)}></div>
    <div class="modal wide">
      <h2>Record release</h2>
      <p class="muted">
        Announces to the fleet on the next heartbeat. Cut + sign the GitHub release first — this
        records it, it doesn't build it.
      </p>
      <label>Version (bare, e.g. 0.2.0)
        <input bind:value={releaseModal.version} placeholder="0.2.0" />
      </label>
      <label>Headline — why a volunteer should want this (required)
        <textarea bind:value={releaseModal.headline} rows="2" placeholder="shown on the worker dashboard"></textarea>
      </label>
      <label>Notes (optional)
        <textarea bind:value={releaseModal.notes} rows="3"></textarea>
      </label>
      <label>Release URL (optional)
        <input bind:value={releaseModal.releaseUrl} placeholder="https://github.com/auspexai/worker/releases/tag/v0.2.0" />
      </label>
      {#if Object.keys(releaseModal.fulfils).length > 0}
        <p class="muted">Fulfils approved requests:</p>
        {#each Object.keys(releaseModal.fulfils) as rid (rid)}
          <label class="check">
            <input type="checkbox" bind:checked={releaseModal.fulfils[rid]} />
            <span class="mono">{rid}</span>
            <span class="muted">{requests.find((r) => r.request_id === rid)?.title ?? ''}</span>
          </label>
        {/each}
      {/if}
      <div class="modal-actions">
        <button onclick={() => (releaseModal = null)}>cancel</button>
        <button class="primary" onclick={submitRelease} disabled={actionLoading || !releaseModal.version.trim() || !releaseModal.headline.trim()}>record + announce</button>
      </div>
    </div>
  {/if}
</main>

<style>
  main { max-width: 1200px; margin: 0 auto; padding: 2em 1.25em; }
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
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.status-pending { background: #78350f; color: #fcd34d; }
  .badge.status-assessed { background: #1e3a5f; color: #93c5fd; }
  .badge.status-approved { background: #14532d; color: #86efac; }
  .badge.status-released { background: #14532d; color: #86efac; }
  .badge.status-declined { background: #7f1d1d; color: #fca5a5; }
  .badge.draft { background: #78350f; color: #fcd34d; }
  .badge.ratified { background: #14532d; color: #86efac; }
  .assessment-cell { max-width: 280px; }
  .assessment-cell dl { margin: 0.5em 0 0; font-size: 0.9em; }
  .assessment-cell dt { color: #9ca3af; font-weight: 600; margin-top: 0.4em; }
  .assessment-cell dd { margin: 0.1em 0 0; color: #d4d4dc; white-space: pre-wrap; }
  details summary { cursor: pointer; font-size: 0.85em; }
  .detail-text { margin: 0.4em 0 0; font-size: 0.9em; white-space: pre-wrap; max-width: 320px; }
  .actions { white-space: nowrap; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  .warn-text { color: #fcd34d; font-size: 0.9em; display: inline-block; margin-left: 0.5em; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.25em 0.65em; border-radius: 4px; cursor: pointer; font: inherit; font-size: 0.85em; }
  button:hover { background: #2a2e3a; }
  button:disabled { opacity: 0.5; cursor: default; }
  button.primary { background: #a78bfa; color: #0a0e1a; border-color: #a78bfa; font-weight: 600; }
  button.danger { background: #7f1d1d; border-color: #7f1d1d; color: #fca5a5; }
  button.inline { margin-left: 0.75em; }
  a { color: #a78bfa; }
  .modal-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); z-index: 10; }
  .modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #1a1e2a; border: 1px solid #2a2e3a; border-radius: 8px; padding: 1.5em; z-index: 11; width: 90%; max-width: 460px; max-height: 85vh; overflow-y: auto; }
  .modal.wide { max-width: 620px; }
  .modal h2 { margin: 0 0 0.5em; color: #fff; font-size: 1.1em; }
  .modal label { display: block; margin: 0.75em 0 0.25em; color: #9ca3af; font-size: 0.9em; }
  .modal label.check { display: flex; gap: 0.5em; align-items: baseline; margin: 0.3em 0; }
  .modal textarea, .modal input:not([type='checkbox']) { width: 100%; padding: 0.4em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; resize: vertical; box-sizing: border-box; }
  .modal-actions { display: flex; gap: 0.75em; justify-content: flex-end; margin-top: 1.25em; }
</style>
