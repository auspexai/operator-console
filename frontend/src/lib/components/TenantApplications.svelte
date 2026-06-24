<script lang="ts">
  // The tenant-application (researcher onboarding) review queue. Folded into the
  // accounts page (the requests page dissolved) — applications already carry an
  // account_id, so review belongs where the account lives. Self-contained:
  // fetches its own data, manages its own modals, and calls `onresolved` so the
  // parent accounts list can refresh its pending-app counts.
  import { onMount } from 'svelte';

  let { onresolved }: { onresolved?: () => void } = $props();

  type TenantApplication = {
    application_id: string;
    account_id: string;
    github_login: string;
    requested_tenant_id: string;
    contact_name: string;
    affiliation: string;
    research_summary: string;
    research_classes?: string[] | null;
    account_existing_tenants?: string[] | null;
    pubkey_hex: string;
    status: string; // pending | approved | declined
    created_at: string;
    resolved_at: string | null;
    resolved_by: string | null;
    resolution_reason: string | null;
    created_tenant_id: string | null;
  };

  let applications = $state<TenantApplication[]>([]);
  let appsError = $state<string | null>(null);
  let actionLoading = $state(false);

  let appApproveModal = $state<{
    applicationId: string;
    githubLogin: string;
    requestedTenantId: string;
    tenantId: string;
  } | null>(null);
  let appDeclineModal = $state<{ applicationId: string; githubLogin: string; reason: string } | null>(
    null,
  );

  const shortHex = (hex: string | null | undefined) => (hex ? `${hex.slice(0, 16)}…` : '—');
  // research_classes ids are snake_case — humanize ("behavioral_drift" → "behavioral drift").
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

  async function load(): Promise<void> {
    try {
      const r = await fetch('/api/v0/proxy/tenant-applications');
      if (r.ok) {
        applications = (await r.json()).applications || [];
        appsError = null;
      } else {
        appsError = `HTTP ${r.status}`;
      }
    } catch (e) {
      appsError = (e as Error).message;
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
      const r = await fetch(`/api/v0/proxy/tenant-applications/${m.applicationId}/actions/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(JSON.stringify(d));
      }
      await load();
      onresolved?.();
    } catch (e) {
      alert(`approve failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  function openAppDecline(app: TenantApplication) {
    appDeclineModal = { applicationId: app.application_id, githubLogin: app.github_login, reason: '' };
  }

  async function submitAppDecline() {
    if (!appDeclineModal) return;
    const m = appDeclineModal;
    appDeclineModal = null;
    actionLoading = true;
    try {
      const r = await fetch(`/api/v0/proxy/tenant-applications/${m.applicationId}/actions/decline`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: m.reason }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(JSON.stringify(d));
      }
      await load();
      onresolved?.();
    } catch (e) {
      alert(`decline failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  onMount(load);
</script>

{#if appsError}
  <p class="muted apps-unavailable">Tenant applications unavailable (coordinator {appsError}).</p>
{:else if pendingApps.length > 0 || resolvedApps.length > 0}
  <section class="apps" id="applications">
    <h2>Tenant applications</h2>
    <p class="muted">
      Researcher onboarding. <em>Approving</em> creates the tenant, binds the applicant's key, and
      links their account in one action; <em>declining</em> requires a reason (audited).
    </p>
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
              <td><strong>@{app.github_login}</strong><br /><span class="muted">{app.contact_name}</span></td>
              <td>{app.affiliation}</td>
              <td class="mono">
                {app.requested_tenant_id}
                {#if app.account_existing_tenants?.length}
                  <div class="multi-tenancy-notice">
                    <span class="notice-label">account already holds:</span>
                    <span class="chips">{#each app.account_existing_tenants as t (t)}<span class="badge existing-tenant">{t}</span>{/each}</span>
                  </div>
                {/if}
              </td>
              <td class="mono" title={app.pubkey_hex}>{shortHex(app.pubkey_hex)}</td>
              <td>
                {#if app.research_classes?.length}<span class="chips">{#each app.research_classes as rc (rc)}<span class="badge rclass">{humanizeClass(rc)}</span>{/each}</span>{/if}
                <details><summary class="muted">view summary</summary><p class="detail-text">{app.research_summary}</p></details>
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
                <td><span class="badge status-{app.status}">{app.status}</span>{#if app.created_tenant_id}<br /><span class="muted mono">→ {app.created_tenant_id}</span>{/if}</td>
                <td><span class="muted">{app.resolved_by ?? '—'}{app.resolution_reason ? `: ${app.resolution_reason}` : ''}</span></td>
                <td class="mono">{app.resolved_at ? new Date(app.resolved_at).toLocaleString() : '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </details>
    {/if}
  </section>
{/if}

{#if appApproveModal}
  <div class="modal-backdrop" onclick={() => (appApproveModal = null)}></div>
  <div class="modal">
    <h2>Approve tenant application</h2>
    <p class="mono">@{appApproveModal.githubLogin}</p>
    <p class="warn-text">
      One action: approving creates the tenant, binds the applicant's key, and links their account.
      There is no separate confirmation step.
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

<style>
  .apps { margin: 0 0 1.5em; }
  .apps h2 { font-size: 1.1em; font-weight: 600; color: #fff; margin: 0 0 0.25em; }
  .apps-unavailable { margin: 0 0 1em; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9em; margin-top: 0.5em; }
  th { text-align: left; padding: 0.5em; border-bottom: 2px solid #2a2e3a; color: #9ca3af; font-weight: 500; }
  td { padding: 0.5em; border-bottom: 1px solid #1a1e2a; vertical-align: top; }
  tr.pending { background: rgba(120, 90, 10, 0.1); }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.82em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .rclass { background: #1e3a5f; color: #93c5fd; }
  .existing-tenant { background: #312e81; color: #c4b5fd; }
  .status-approved { background: #14532d; color: #86efac; }
  .status-declined { background: #7f1d1d; color: #fca5a5; }
  .chips { display: inline-flex; gap: 0.3em; flex-wrap: wrap; }
  .multi-tenancy-notice { margin-top: 0.4em; font-size: 0.85em; }
  .notice-label { color: #fbbf24; margin-right: 0.4em; }
  .detail-text { white-space: pre-wrap; color: #cdd5e6; font-size: 0.85em; max-width: 40ch; margin: 0.4em 0 0; }
  .resolved-apps { margin-top: 1em; }
  .resolved-apps summary { cursor: pointer; }
  .actions { white-space: nowrap; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.25em 0.65em; border-radius: 4px; cursor: pointer; font: inherit; font-size: 0.85em; }
  button:hover { background: #2a2e3a; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  button.primary { background: #a78bfa; color: #0a0e1a; border-color: #a78bfa; font-weight: 600; }
  button.primary:hover { background: #c4b5fd; }
  button.danger { background: #7f1d1d; border-color: #7f1d1d; color: #fca5a5; }
  button.danger:hover { background: #991b1b; }
  .modal-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); z-index: 10; }
  .modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #1a1e2a; border: 1px solid #2a2e3a; border-radius: 8px; padding: 1.5em; z-index: 11; width: 90%; max-width: 500px; }
  .modal h2 { margin: 0 0 0.5em; color: #fff; font-size: 1.1em; }
  .modal label { display: block; margin: 0.75em 0 0.25em; color: #9ca3af; font-size: 0.9em; }
  .modal input, .modal textarea { width: 100%; padding: 0.4em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; font-size: 0.9em; resize: vertical; }
  .modal input:focus, .modal textarea:focus { outline: none; border-color: #a78bfa; }
  .warn-text { color: #fbbf24; font-size: 0.9em; margin: 0.25em 0 0.5em; }
  .modal-actions { display: flex; gap: 0.75em; justify-content: flex-end; margin-top: 1.25em; }
</style>
