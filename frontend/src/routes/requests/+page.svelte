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

  // Tenant applications (onboarding review queue): the maintainer-side end of
  // the website application form. Approve is ONE action on the coordinator —
  // tenant created + applicant key bound + account linked.
  type TenantApplication = {
    application_id: string;
    account_id: string;
    github_login: string;
    requested_tenant_id: string;
    contact_name: string;
    affiliation: string;
    research_summary: string;
    // Optional self-declared research classes (e.g. behavioral_drift,
    // eval_sweeps); older coordinators omit the field entirely.
    research_classes?: string[] | null;
    // Multi-tenancy review context: tenant ids already linked to the
    // applicant's account. [] / absent = first tenancy; older coordinators
    // omit the field entirely.
    account_existing_tenants?: string[] | null;
    pubkey_hex: string;
    status: string; // pending | approved | declined
    created_at: string;
    resolved_at: string | null;
    resolved_by: string | null;
    resolution_reason: string | null;
    created_tenant_id: string | null;
  };

  let requests = $state<SoftwareRequest[]>([]);
  let applications = $state<TenantApplication[]>([]);
  let appsError = $state<string | null>(null);
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

  let appApproveModal = $state<{
    applicationId: string;
    githubLogin: string;
    requestedTenantId: string;
    tenantId: string; // editable; sent as tenant_id_override when changed
  } | null>(null);

  let appDeclineModal = $state<{
    applicationId: string;
    githubLogin: string;
    reason: string;
  } | null>(null);

  type AgentStatus = {
    installed: boolean;
    model?: string;
    api_key_present?: boolean;
    max_drafts_per_tick?: number;
    timer_active?: boolean;
  };
  let agent = $state<AgentStatus | null>(null);
  let capDraft = $state('5');
  let capSaving = $state(false);

  // §9 #48: the experiment-assessment agent (the auto-approval ENGINE, rage-local)
  // and the GATE (coordinator-authoritative). The engine triages; the gate decides
  // whether routine experiments clear without a click. Off = review-only.
  type ExpAgentStatus = {
    installed: boolean;
    timer_active?: boolean;
    timer_next?: string | null;
    last_run_exit?: string | null;
  };
  type GatePolicy = {
    enabled: boolean;
    min_tier: number;
    updated_at?: string | null;
    updated_by?: string | null;
    update_reason?: string | null;
  };
  let expAgent = $state<ExpAgentStatus | null>(null);
  let gate = $state<GatePolicy | null>(null);
  let gateChoice = $state('off'); // 'off' | 't2' | 't3'
  let gateSaving = $state(false);
  // The select value that reflects the currently-saved gate (to disable a no-op save).
  let gateSaved = $derived(gate ? (gate.enabled ? (gate.min_tier >= 3 ? 't3' : 't2') : 'off') : 'off');

  // The assessment agent folds its baseline-classification verdict into the
  // front of the summary as "[VERDICT] evidence — ...". Surface it as a chip
  // so the maintainer sees new-vs-covered at a glance without expanding.
  const VERDICTS = ['NEW', 'DUPLICATE', 'ALREADY_PROVIDED', 'PARTIALLY_COVERED'] as const;
  function verdictOf(req: SoftwareRequest): string | null {
    const m = req.assessment?.summary?.match(/^\[([A-Z_]+)\]/);
    return m && (VERDICTS as readonly string[]).includes(m[1]) ? m[1] : null;
  }

  async function loadAgent() {
    try {
      const r = await fetch('/api/v0/agent/assessment');
      if (r.ok) {
        agent = await r.json();
        capDraft = String(agent?.max_drafts_per_tick ?? 0);
      }
    } catch {
      /* agent card is best-effort */
    }
  }

  // The drafts/tick number IS the spend control: 0 = off (no drafts, no LLM
  // call, $0); any positive number is the per-tick cap.
  async function saveCap() {
    const n = Math.max(0, Math.min(100, Math.round(Number(capDraft) || 0)));
    capDraft = String(n);
    capSaving = true;
    try {
      const r = await fetch('/api/v0/agent/assessment/cap', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_drafts_per_tick: n }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await loadAgent();
    } catch (e) {
      alert(`update failed: ${(e as Error).message}`);
    } finally {
      capSaving = false;
    }
  }

  async function loadExpAgent() {
    try {
      const r = await fetch('/api/v0/agent/experiment-assessment');
      if (r.ok) expAgent = await r.json();
    } catch {
      /* engine card is best-effort */
    }
  }

  async function loadGate() {
    try {
      const r = await fetch('/api/v0/proxy/assessment-policy');
      if (r.ok) {
        gate = await r.json();
        gateChoice = gateSaved;
      }
    } catch {
      /* gate card is best-effort */
    }
  }

  async function saveGate() {
    const enabled = gateChoice !== 'off';
    const min_tier = gateChoice === 't3' ? 3 : 2;
    gateSaving = true;
    try {
      const r = await fetch('/api/v0/proxy/assessment-policy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, min_tier }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await loadGate();
    } catch (e) {
      alert(`gate update failed: ${(e as Error).message}`);
    } finally {
      gateSaving = false;
    }
  }

  // Promotion-gate certifications (RFC 0001 / Ethics §6.7) — the OTHER auto-approval
  // lever: certified profiles auto-run by their certification, independent of the
  // routine-tier gate above. Read-only list + revoke; issuing is a CLI/host act.
  type Cert = {
    package_sha256: string;
    snapshot_version: string;
    tenant_id: string;
    profile_name: string;
    status: string;
    replication_floor: number;
    advisor: string | null;
  };
  let certs = $state<Cert[]>([]);
  let activeCerts = $derived(certs.filter((c) => c.status === 'certified'));

  async function loadCerts() {
    try {
      const r = await fetch('/api/v0/proxy/certifications');
      if (r.ok) certs = (await r.json()).certifications ?? [];
    } catch {
      /* certifications panel is best-effort */
    }
  }

  async function revokeCert(c: Cert) {
    const reason = prompt(
      `Revoke certification for ${c.tenant_id}/${c.profile_name} @ ${c.snapshot_version}?\n\n` +
        `Its runs stop auto-clearing and revert to review. Reason (required):`,
    );
    if (!reason || !reason.trim()) return;
    try {
      const r = await fetch(`/api/v0/proxy/certifications/${c.package_sha256}/revoke`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: reason.trim() }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await loadCerts();
    } catch (e) {
      alert(`revoke failed: ${(e as Error).message}`);
    }
  }

  async function loadAll(silent = false): Promise<boolean> {
    if (!silent) loading = true;
    try {
      const [reqR, appR] = await Promise.all([
        fetch('/api/v0/proxy/software-requests'),
        fetch('/api/v0/proxy/tenant-applications'),
      ]);
      if (!reqR.ok) throw new Error(`software-requests HTTP ${reqR.status}`);
      requests = (await reqR.json()).requests || [];
      // Section-level degrade: a coordinator without the tenant-applications
      // routes yet shouldn't take down the software/model queues.
      if (appR.ok) {
        applications = (await appR.json()).applications || [];
        appsError = null;
      } else {
        appsError = `HTTP ${appR.status}`;
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

  function openAppApprove(app: TenantApplication) {
    appApproveModal = {
      applicationId: app.application_id,
      githubLogin: app.github_login,
      requestedTenantId: app.requested_tenant_id,
      tenantId: app.requested_tenant_id,
    };
  }

  async function submitAppApprove() {
    if (!appApproveModal) return;
    const m = appApproveModal;
    appApproveModal = null;
    actionLoading = true;
    try {
      const tenantId = m.tenantId.trim();
      const body =
        tenantId && tenantId !== m.requestedTenantId ? { tenant_id_override: tenantId } : {};
      const r = await fetch(
        `/api/v0/proxy/tenant-applications/${m.applicationId}/actions/approve`,
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
      await loadAll(true);
    } catch (e) {
      alert(`approve failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  function openAppDecline(app: TenantApplication) {
    appDeclineModal = {
      applicationId: app.application_id,
      githubLogin: app.github_login,
      reason: '',
    };
  }

  async function submitAppDecline() {
    if (!appDeclineModal) return;
    const m = appDeclineModal;
    appDeclineModal = null;
    actionLoading = true;
    try {
      const r = await fetch(
        `/api/v0/proxy/tenant-applications/${m.applicationId}/actions/decline`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: m.reason }),
        },
      );
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(JSON.stringify(d));
      }
      await loadAll(true);
    } catch (e) {
      alert(`decline failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  // Truncated pubkey display (mirrors the accounts-page tenant-linkage convention).
  const shortHex = (hex: string | null | undefined) => (hex ? `${hex.slice(0, 16)}…` : '—');

  // research_classes ids are snake_case — humanize for display ("behavioral_drift"
  // → "behavioral drift").
  const humanizeClass = (id: string) => id.replace(/_/g, ' ');

  let pendingApps = $derived(
    applications
      .filter((a) => a.status === 'pending')
      .sort((a, b) => b.created_at.localeCompare(a.created_at)),
  );
  let resolvedApps = $derived(
    applications
      .filter((a) => a.status !== 'pending')
      .sort((a, b) => (b.resolved_at ?? '').localeCompare(a.resolved_at ?? '')),
  );

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

  onMount(() => {
    loadAll().then((ok) => (live = ok));
    loadAgent();
    loadExpAgent();
    loadGate();
    loadCerts();
    return autoRefresh({
      refresh: () => loadAll(true),
      setLive: (v) => (live = v),
      types: [
        'requirement.submitted',
        'requirement.assessed',
        'requirement.resolved',
        'release.published',
        // Tenant-application doorbells (coordinator side in flight; harmless
        // if never emitted — the 30s poll stays the source of truth).
        'application.submitted',
        'application.resolved',
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
    <!-- Tenant applications (onboarding review queue) -->
    <h2 class="section">Tenant applications</h2>
    <p class="muted">
      Researcher onboarding: each application carries the applicant's GitHub identity and their
      Ed25519 public key. <em>Approving</em> creates the tenant, binds the key, and links the
      account in one action; <em>declining</em> requires a reason (audited).
    </p>
    {#if appsError}
      <p class="muted">Tenant applications unavailable (coordinator {appsError}).</p>
    {:else}
      {#if pendingApps.length === 0}
        <p class="muted">No pending applications.</p>
      {:else}
        <table>
          <thead>
            <tr><th>applicant</th><th>affiliation</th><th>requested tenant</th><th>pubkey</th><th>research summary</th><th>created</th><th></th></tr>
          </thead>
          <tbody>
            {#each pendingApps as app (app.application_id)}
              <tr class="pending">
                <td>
                  <strong>@{app.github_login}</strong><br />
                  <span class="muted">{app.contact_name}</span>
                </td>
                <td>{app.affiliation}</td>
                <td class="mono">
                  {app.requested_tenant_id}
                  {#if app.account_existing_tenants?.length}
                    <!-- Multi-tenancy notice: approving here grants an ADDITIONAL
                         tenancy to an account that already holds one — make it a
                         knowing act, not a surprise in the accounts list later. -->
                    <div class="multi-tenancy-notice">
                      <span class="notice-label">account already holds:</span>
                      <span class="chips">
                        {#each app.account_existing_tenants as t (t)}
                          <span class="badge existing-tenant">{t}</span>
                        {/each}
                      </span>
                    </div>
                  {/if}
                </td>
                <td class="mono" title={app.pubkey_hex}>{shortHex(app.pubkey_hex)}</td>
                <td>
                  {#if app.research_classes?.length}
                    <span class="chips">
                      {#each app.research_classes as rc (rc)}
                        <span class="badge rclass">{humanizeClass(rc)}</span>
                      {/each}
                    </span>
                  {/if}
                  <details>
                    <summary class="muted">view summary</summary>
                    <p class="detail-text">{app.research_summary}</p>
                  </details>
                </td>
                <td class="mono">{new Date(app.created_at).toLocaleString()}</td>
                <td class="actions">
                  <button class="primary" onclick={() => openAppApprove(app)} disabled={actionLoading}>approve</button>
                  <button class="danger" onclick={() => openAppDecline(app)} disabled={actionLoading}>decline</button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
      {#if resolvedApps.length > 0}
        <details class="resolved-apps">
          <summary class="muted">resolved applications ({resolvedApps.length})</summary>
          <table>
            <thead>
              <tr><th>applicant</th><th>requested tenant</th><th>status</th><th>resolution</th><th>resolved</th></tr>
            </thead>
            <tbody>
              {#each resolvedApps as app (app.application_id)}
                <tr>
                  <td><strong>@{app.github_login}</strong> <span class="muted">{app.contact_name}</span></td>
                  <td class="mono">{app.requested_tenant_id}</td>
                  <td>
                    <span class="badge status-{app.status}">{app.status}</span>
                    {#if app.created_tenant_id}<br /><span class="muted mono">→ {app.created_tenant_id}</span>{/if}
                  </td>
                  <td><span class="muted">{app.resolved_by ?? '—'}{app.resolution_reason ? `: ${app.resolution_reason}` : ''}</span></td>
                  <td class="mono">{app.resolved_at ? new Date(app.resolved_at).toLocaleString() : '—'}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </details>
      {/if}
    {/if}

    <!-- Software-requirements queue -->
    <h2 class="section">Software-requirements queue</h2>
    <p class="muted">
      Code-plane demand: capabilities the worker baseline doesn't provide. Review the
      dependencies/security/alternatives assessment, then <em>approve</em> or <em>decline</em>
      (mandatory reason). Approving without a ratified assessment records a gate override.
      Releases announce themselves: publishing a GitHub release notifies the fleet directly
      (<code>Fulfils: swr-…</code> in the release description closes approved requests) — see the
      <a href="https://github.com/auspexai/worker/releases" target="_blank" rel="noreferrer">releases on GitHub ↗</a>.
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
                  {#if verdictOf(req)}
                    <span class="badge verdict-{verdictOf(req)}">{verdictOf(req)?.replace(/_/g, ' ')}</span>
                  {/if}
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

    <!-- Agents: one control each; the control's value IS the state -->
    {#if agent || gate}
      <h2 class="section">Agents</h2>

      <!-- Software-request drafting — the number is the spend control (0 = off) -->
      {#if agent}
        <div class="agent">
          <div class="agent-name">Software-request drafting</div>
          <div class="agent-sub">{agent.model ?? 'LLM'} · ~$0.15/draft</div>
          {#if !agent.installed}
            <span class="muted">Not installed on this host.</span>
          {:else}
            <div class="agent-ctl">
              <label class="cap-label">max
                <input
                  class="cap-input"
                  type="number"
                  min="0"
                  max="100"
                  bind:value={capDraft}
                  onchange={saveCap}
                  disabled={capSaving}
                />
                drafts/tick</label>
              {#if Number(capDraft) > 0}
                <span class="cost">≈ ${(Number(capDraft) * 0.15).toFixed(2)}/tick</span>
              {:else}
                <span class="cost">off · $0</span>
              {/if}
              <span class="hint">(0 = off)</span>
            </div>
            {#if !agent.api_key_present}<div class="agent-warn">no API key on host — won't draft until one is set</div>{/if}
            {#if !agent.timer_active}<div class="agent-warn">service not running on host</div>{/if}
          {/if}
        </div>
      {/if}

      <!-- Auto-approval — what runs without your approval (two levers) -->
      {#if gate}
        <div class="agent">
          <div class="agent-name">Auto-approval — what runs without your approval</div>
          <div class="agent-sub">no LLM · no cost</div>

          <!-- Lever 1: certified profiles — vetted/declawed, auto-run for everyone -->
          <div class="gate-block">
            <div class="gate-block-h">
              Certified profiles <span class="muted">— always auto-run (vetted, declawed)</span>
            </div>
            {#if activeCerts.length === 0}
              <p class="hint">
                None certified. Certify a starter on the coordinator (<code>certification issue</code>)
                to make its runs auto-clear.
              </p>
            {:else}
              <table class="cert-table">
                <tbody>
                  {#each activeCerts as c (c.package_sha256)}
                    <tr>
                      <td class="mono">{c.tenant_id}/{c.profile_name}</td>
                      <td class="mono muted">{c.snapshot_version}</td>
                      <td class="muted">floor {c.replication_floor}</td>
                      <td class="muted">{c.advisor ? `advisor: ${c.advisor}` : 'low-risk'}</td>
                      <td><button class="linkish" onclick={() => revokeCert(c)}>revoke</button></td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            {/if}
          </div>

          <!-- Lever 2: the frontier — uncertified routine from trusted tenants -->
          <div class="gate-block">
            <div class="gate-block-h">
              Trusted tenants' uncertified research
              <span class="muted">— the frontier that produces certifiable profiles</span>
            </div>
            <div class="agent-ctl">
              <select
                class="cap-input gate-select"
                bind:value={gateChoice}
                onchange={saveGate}
                disabled={gateSaving}
              >
                <option value="off">Off — I review every uncertified experiment</option>
                <option value="t2">Auto-approve routine from trusted tenants (T2+)</option>
                <option value="t3">Auto-approve routine from vetted tenants only (T3)</option>
              </select>
            </div>
            <span class="hint"
              >does not affect certified profiles · the agent still assesses + queues every
              experiment; “off” only withholds the auto-approve</span
            >
          </div>
          {#if expAgent && !expAgent.timer_active}<div class="agent-warn">
              engine stopped — auto-approval won't run until it's started
            </div>{/if}
        </div>
      {/if}
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

  {#if appApproveModal}
    <div class="modal-backdrop" onclick={() => (appApproveModal = null)}></div>
    <div class="modal">
      <h2>Approve tenant application</h2>
      <p class="mono">@{appApproveModal.githubLogin}</p>
      <p class="warn-text">
        One action: approving creates the tenant, binds the applicant's key, and links their
        account. There is no separate confirmation step.
      </p>
      <label>Tenant id (edit to override the requested id)
        <input bind:value={appApproveModal.tenantId} />
      </label>
      {#if appApproveModal.tenantId.trim() && appApproveModal.tenantId.trim() !== appApproveModal.requestedTenantId}
        <p class="muted">
          Overriding requested <span class="mono">{appApproveModal.requestedTenantId}</span> →
          <span class="mono">{appApproveModal.tenantId.trim()}</span>
        </p>
      {/if}
      <div class="modal-actions">
        <button onclick={() => (appApproveModal = null)}>cancel</button>
        <button class="primary" onclick={submitAppApprove} disabled={actionLoading || !appApproveModal.tenantId.trim()}>approve</button>
      </div>
    </div>
  {/if}

  {#if appDeclineModal}
    <div class="modal-backdrop" onclick={() => (appDeclineModal = null)}></div>
    <div class="modal">
      <h2>Decline tenant application</h2>
      <p class="mono">@{appDeclineModal.githubLogin}</p>
      <label>Reason (required)
        <textarea bind:value={appDeclineModal.reason} rows="3" placeholder="recorded in the audit log"></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (appDeclineModal = null)}>cancel</button>
        <button class="danger" onclick={submitAppDecline} disabled={actionLoading || !appDeclineModal.reason.trim()}>decline</button>
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
  .badge.verdict-NEW { background: #14532d; color: #86efac; border: 1px solid #22c55e; }
  .badge.verdict-ALREADY_PROVIDED { background: #1e3a5f; color: #93c5fd; }
  .badge.verdict-DUPLICATE { background: #3f3f46; color: #d4d4d8; }
  .badge.verdict-PARTIALLY_COVERED { background: #78350f; color: #fcd34d; }
  .badge.draft { background: #78350f; color: #fcd34d; }
  .badge.ratified { background: #14532d; color: #86efac; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.3em; margin-bottom: 0.35em; max-width: 320px; }
  .badge.rclass { background: #2e1065; color: #c4b5fd; font-size: 0.8em; }
  .multi-tenancy-notice { margin-top: 0.45em; padding: 0.35em 0.5em; background: rgba(120, 53, 15, 0.3); border: 1px solid #b45309; border-radius: 4px; max-width: 240px; }
  .multi-tenancy-notice .notice-label { display: block; color: #fcd34d; font-weight: 600; margin-bottom: 0.3em; }
  .multi-tenancy-notice .chips { margin-bottom: 0; }
  .badge.existing-tenant { background: #78350f; color: #fcd34d; border: 1px solid #d97706; }
  .assessment-cell { max-width: 280px; }
  .assessment-cell dl { margin: 0.5em 0 0; font-size: 0.9em; }
  .assessment-cell dt { color: #9ca3af; font-weight: 600; margin-top: 0.4em; }
  .assessment-cell dd { margin: 0.1em 0 0; color: #d4d4dc; white-space: pre-wrap; }
  details summary { cursor: pointer; font-size: 0.85em; }
  .resolved-apps { margin: 0.5em 0 1em; }
  .resolved-apps table { margin-top: 0.5em; }
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
  .cap-label { color: #9ca3af; }
  .cap-input { width: 4.5em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; padding: 0.2em 0.4em; font: inherit; margin: 0 0.3em; }
  .gate-select { width: auto; margin: 0; }

  /* Agents — one control each; the control's value is the state. Color is
     reserved for warnings only, so nothing reads as a false on/off signal. */
  .agent { margin: 0.7em 0 1em; }
  .agent-name { font-weight: 600; color: #d4d4dc; }
  .agent-sub { color: #6b7280; font-size: 0.85em; margin-top: 0.1em; }
  .agent-ctl { display: flex; align-items: center; gap: 0.6em; margin-top: 0.45em; flex-wrap: wrap; }
  .cost { color: #cbd5e1; font-variant-numeric: tabular-nums; }
  .hint { color: #6b7280; font-size: 0.85em; }
  .gate-block { margin: 0.6em 0 0.4em; padding-left: 0.7em; border-left: 2px solid #2a2a35; }
  .gate-block-h { font-size: 0.92em; color: #cbd5e1; }
  .cert-table { margin-top: 0.35em; border-collapse: collapse; font-size: 0.85em; }
  .cert-table td { padding: 0.12em 0.7em 0.12em 0; vertical-align: middle; }
  .linkish { background: none; border: none; color: #a78bfa; cursor: pointer; padding: 0; font: inherit; }
  .linkish:hover { text-decoration: underline; }
  .agent-warn { margin-top: 0.35em; color: #fbbf24; font-size: 0.9em; }
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
