<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import Nav from '$lib/components/Nav.svelte';
  import LiveDot from '$lib/components/LiveDot.svelte';
  import { autoRefresh, type LiveEvent } from '$lib/live';

  type Account = {
    account_id: string;
    idp: string;
    idp_sub: string;
    display_name: string;
    trust_tier: number;
    trust_tier_name: string;
    created_at: string;
    retired_at: string | null;
    suspended_at: string | null;
    suspension_reason: string | null;
    identity_verified_at: string | null;
    identity_verification_method: string | null;
  };

  type ReceiptStats = {
    account_id: string;
    current_tier: number;
    current_tier_name: string;
    total_receipts: number;
    distinct_experiments: number;
    distinct_tenants: number;
    first_receipt_at: string | null;
    last_receipt_at: string | null;
    eligibility_by_tier: any[];
  };

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
  };

  // Full tenant facts (the former standalone /tenants page collapsed into the
  // Accounts pages — account = the root, one home per fact). The operator
  // credential sees contact_email + maintainer_pubkey in the tenants LIST
  // response.
  type Tenant = {
    tenant_id: string;
    display_name: string | null;
    description: string | null;
    contact_public: string | null;
    contact_email: string | null;
    registered_at: string | null;
    maintainer_pubkey: string | null;
  };

  const tierNames: Record<number, string> = {
    0: 'T0 anonymous',
    1: 'T1 authenticated',
    2: 'T2 trusted',
    3: 'T3 vetted',
  };

  // page.params.id is `string | undefined` in the SvelteKit types but always
  // present for this [id] route at runtime; coalesce so it types as string.
  let accountId = $derived(page.params.id ?? '');
  let account = $state<Account | null>(null);
  let receiptStats = $state<ReceiptStats | null>(null);
  let boundWorkers = $state<Worker[]>([]);
  // Account → tenants, with full tenant facts (account ↔ tenants ↔ workers all
  // on this page). The tenants LIST response carries no account_id
  // (operator-only field, exposed via the per-tenant linkage endpoint), so
  // join client-side: fetch each tenant's linkage and keep the full facts of
  // the ones bound to this account.
  let linkedTenants = $state<Tenant[]>([]);
  let pendingAppCount = $state(0);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let actionLoading = $state(false);
  let live = $state(false);

  const shortHex = (hex: string | null | undefined) => (hex ? `${hex.slice(0, 16)}…` : '—');

  let tierModal = $state<{
    action: 'promote' | 'demote';
    targetTier: number;
    reason: string;
  } | null>(null);

  async function loadAccount(silent = false): Promise<boolean> {
    if (!silent) loading = true;
    try {
      const [accountsRes, statsRes, workersRes, tenantsRes, appsRes] = await Promise.all([
        fetch('/api/v0/proxy/accounts'),
        fetch(`/api/v0/proxy/accounts/${encodeURIComponent(accountId)}/receipt-stats`),
        fetch('/api/v0/proxy/workers'),
        fetch('/api/v0/proxy/tenants'),
        fetch('/api/v0/proxy/tenant-applications'),
      ]);
      if (!accountsRes.ok) throw new Error(`Accounts: HTTP ${accountsRes.status}`);
      const accountsBody = await accountsRes.json();
      const allAccounts: Account[] = accountsBody.accounts || accountsBody || [];
      account = allAccounts.find(a => a.account_id === accountId) ?? null;
      if (!account) throw new Error(`Account ${accountId} not found`);

      if (statsRes.ok) {
        receiptStats = await statsRes.json();
      }

      if (workersRes.ok) {
        const workersBody = await workersRes.json();
        const allWorkers: Worker[] = workersBody.workers || workersBody || [];
        boundWorkers = allWorkers.filter(w => w.account_id === accountId);
      }

      // Tenant count is small, so the per-tenant linkage fan-out is cheap;
      // best-effort like the stats/workers sections above.
      if (tenantsRes.ok) {
        const tenantsBody = await tenantsRes.json();
        const allTenants: Tenant[] = tenantsBody.tenants || tenantsBody || [];
        const linkages = await Promise.all(
          allTenants.map(async (t) => {
            try {
              const r = await fetch(`/api/v0/proxy/tenants/${encodeURIComponent(t.tenant_id)}/linkage`);
              return r.ok ? ((await r.json()) as { account_id?: string }) : null;
            } catch {
              return null;
            }
          }),
        );
        linkedTenants = allTenants.filter((_, i) => linkages[i]?.account_id === accountId);
      }

      if (appsRes.ok) {
        const apps: { account_id?: string; status?: string }[] = (await appsRes.json()).applications || [];
        pendingAppCount = apps.filter((a) => a.status === 'pending' && a.account_id === accountId).length;
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

  function showTierModal(action: 'promote' | 'demote') {
    if (!account) return;
    tierModal = {
      action,
      targetTier: action === 'promote' ? Math.min(account.trust_tier + 1, 3) : Math.max(account.trust_tier - 1, 0),
      reason: '',
    };
  }

  async function submitTierChange() {
    if (!tierModal) return;
    actionLoading = true;
    try {
      const r = await fetch(`/api/v0/proxy/accounts/${encodeURIComponent(accountId)}/actions/${tierModal.action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_tier: tierModal.targetTier, reason: tierModal.reason }),
      });
      if (!r.ok) {
        const detail = await r.json();
        throw new Error(JSON.stringify(detail));
      }
      const result = await r.json();
      tierModal = null;
      if (result.gate_override && result.gate_warnings?.length) {
        alert(`Tier change applied with gate override:\n\n${result.gate_warnings.map((w: string) => `• ${w}`).join('\n')}\n\nThis override is recorded in the audit log.`);
      }
      await loadAccount();
    } catch (e) {
      alert(`${tierModal?.action} failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  let suspendModal = $state<{ reason: string } | null>(null);

  async function submitSuspend() {
    if (!suspendModal) return;
    actionLoading = true;
    try {
      const r = await fetch(`/api/v0/proxy/accounts/${encodeURIComponent(accountId)}/actions/suspend`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: suspendModal.reason }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      suspendModal = null;
      await loadAccount();
    } catch (e) {
      alert(`Suspend failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  let unsuspendModal = $state<{ reason: string } | null>(null);

  async function submitUnsuspend() {
    if (!unsuspendModal) return;
    actionLoading = true;
    try {
      const r = await fetch(`/api/v0/proxy/accounts/${encodeURIComponent(accountId)}/actions/unsuspend`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: unsuspendModal.reason }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      unsuspendModal = null;
      await loadAccount();
    } catch (e) {
      alert(`Unsuspend failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  onMount(() => {
    loadAccount().then((ok) => (live = ok));
    // Poll is the truth, the SSE doorbell is a hint. Re-snapshot on a bound
    // worker's status change (scoped to this account) or any receipt issuance (a
    // receipt can auto-promote this account — shifting the tier — and it's low
    // frequency, so we don't filter it by account).
    return autoRefresh({
      refresh: () => loadAccount(true),
      setLive: (v) => (live = v),
      types: ['worker.status', 'receipt.issued'],
      eventFilter: (ev: LiveEvent) =>
        ev.type === 'receipt.issued' ||
        (ev.data as { account_id?: string } | null)?.account_id === accountId,
    });
  });
</script>

<svelte:head>
  <title>Account {accountId} — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> account detail
      {#if !loading}<LiveDot {live} />{/if}
    </h1>
  </header>
  <Nav />

  <p class="breadcrumb"><a href="/accounts">accounts</a> / <span class="mono">{accountId}</span></p>

  {#if loading}
    <p class="muted">Loading account...</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else if account}
    <section class="card">
      <h2>Metadata</h2>
      <dl>
        <dt>account_id</dt><dd class="mono">{account.account_id}</dd>
        <dt>identity provider</dt><dd><span class="badge idp-badge">{account.idp}</span></dd>
        <dt>IDP subject</dt><dd class="mono">{account.idp_sub}</dd>
        <dt>display name</dt><dd>{account.display_name || '—'}</dd>
        <dt>trust tier</dt>
        <dd><span class="badge tier-{account.trust_tier}">{tierNames[account.trust_tier] ?? `T${account.trust_tier}`}</span></dd>
        <dt>created</dt><dd class="mono">{new Date(account.created_at).toLocaleString()}</dd>
        <dt>status</dt>
        <dd>
          {#if account.retired_at}
            <span class="badge retired-badge">retired</span>
            <span class="mono muted"> — {new Date(account.retired_at).toLocaleString()}</span>
          {:else if account.suspended_at}
            <span class="badge suspended-badge">suspended</span>
            <span class="mono muted"> — {new Date(account.suspended_at).toLocaleString()}</span>
            {#if account.suspension_reason}
              <div class="muted reason">reason: {account.suspension_reason}</div>
            {/if}
          {:else}
            <span class="badge ok">active</span>
          {/if}
        </dd>
        <dt>identity verified</dt>
        <dd>
          {#if account.identity_verified_at}
            <span class="badge ok">verified</span>
            <span class="mono muted"> — {account.identity_verification_method ?? 'unknown method'}, {new Date(account.identity_verified_at).toLocaleString()}</span>
          {:else}
            <span class="muted">not verified</span>
          {/if}
        </dd>
      </dl>
    </section>

    {#if receiptStats}
      <section class="card">
        <h2>Receipt statistics</h2>
        <dl>
          <dt>total receipts</dt><dd>{receiptStats.total_receipts}</dd>
          <dt>distinct experiments</dt><dd>{receiptStats.distinct_experiments}</dd>
          <dt>distinct tenants</dt><dd>{receiptStats.distinct_tenants}</dd>
          <dt>first receipt</dt><dd class="mono">{receiptStats.first_receipt_at ? new Date(receiptStats.first_receipt_at).toLocaleString() : '—'}</dd>
          <dt>last receipt</dt><dd class="mono">{receiptStats.last_receipt_at ? new Date(receiptStats.last_receipt_at).toLocaleString() : '—'}</dd>
        </dl>
      </section>

      {#if receiptStats.eligibility_by_tier && receiptStats.eligibility_by_tier.length > 0}
        <section class="card">
          <h2>Tier eligibility</h2>
          <table class="inner-table">
            <thead>
              <tr>
                <th>tier</th>
                <th>eligible</th>
                <th>details</th>
              </tr>
            </thead>
            <tbody>
              {#each receiptStats.eligibility_by_tier as elig}
                <tr>
                  <td><span class="badge tier-{elig.tier ?? elig.target_tier ?? 0}">{tierNames[elig.tier ?? elig.target_tier ?? 0] ?? `T${elig.tier ?? elig.target_tier ?? 0}`}</span></td>
                  <td>
                    {#if elig.eligible}
                      <span class="badge ok">eligible</span>
                    {:else}
                      <span class="badge">not eligible</span>
                    {/if}
                  </td>
                  <td class="muted">{elig.reason ?? elig.details ?? '—'}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </section>
      {/if}
    {/if}

    <!-- Rendered only when this account has tenants or pending applications
         (most volunteer accounts have neither). -->
    {#if linkedTenants.length > 0 || pendingAppCount > 0}
      <section class="card">
        <h2>Linked tenants</h2>
        {#if linkedTenants.length > 0}
          {#each linkedTenants as t (t.tenant_id)}
            <div class="tenant-block">
              <div class="tenant-head">
                <span class="badge tenant-badge">tenant</span>
                <span class="mono tenant-id">{t.tenant_id}</span>
                {#if t.display_name}<span class="tenant-name">{t.display_name}</span>{/if}
              </div>
              <dl class="tenant-facts">
                <dt>contact</dt><dd>{t.contact_email ?? t.contact_public ?? '—'}</dd>
                <dt>registered</dt><dd class="mono">{t.registered_at ? new Date(t.registered_at).toLocaleString() : '—'}</dd>
                <dt>maintainer pubkey</dt><dd class="mono" title={t.maintainer_pubkey ?? undefined}>{shortHex(t.maintainer_pubkey)}</dd>
                {#if t.description}<dt>description</dt><dd>{t.description}</dd>{/if}
              </dl>
            </div>
          {/each}
        {:else}
          <p class="muted">No tenants linked to this account.</p>
        {/if}
        {#if pendingAppCount > 0}
          <p class="pending-line">
            <a href="/requests" class="pending-chip">{pendingAppCount} pending tenant application{pendingAppCount === 1 ? '' : 's'}</a>
            <span class="muted">— review on the requests page</span>
          </p>
        {/if}
      </section>
    {/if}

    <section class="card">
      <h2>Bound workers</h2>
      {#if boundWorkers.length === 0}
        <p class="muted">No workers bound to this account.</p>
      {:else}
        <table class="inner-table">
          <thead>
            <tr>
              <th>worker_id</th>
              <th>tier</th>
              <th>last heartbeat</th>
              <th>status</th>
            </tr>
          </thead>
          <tbody>
            {#each boundWorkers as w}
              <tr>
                <td class="mono"><a href="/workers" class="id-link">{w.worker_id}</a></td>
                <td><span class="badge tier-{w.trust_tier}">{tierNames[w.trust_tier] ?? `T${w.trust_tier}`}</span></td>
                <td class="mono">{w.last_heartbeat_at ? new Date(w.last_heartbeat_at).toLocaleString() : '—'}</td>
                <td>
                  {#if w.retired_at}
                    <span class="badge retired-badge">retired</span>
                  {:else if w.quarantined_at}
                    <span class="badge quarantine-badge">quarantined</span>
                  {:else if !w.last_heartbeat_at || (Date.now() - new Date(w.last_heartbeat_at).getTime()) > 180_000}
                    <span class="badge stale-badge">offline</span>
                  {:else}
                    <span class="badge ok">active</span>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        <p class="muted">{boundWorkers.length} worker(s)</p>
      {/if}
    </section>

    <section class="card">
      <h2>Actions</h2>
      <div class="action-row">
        {#if !account.retired_at}
          {#if account.trust_tier < 3}
            <button class="primary" onclick={() => showTierModal('promote')} disabled={actionLoading}>promote</button>
          {/if}
          {#if account.trust_tier > 0}
            <button onclick={() => showTierModal('demote')} disabled={actionLoading}>demote</button>
          {/if}
          {#if account.suspended_at}
            <button onclick={() => (unsuspendModal = { reason: '' })} disabled={actionLoading}>unsuspend</button>
          {:else}
            <button class="danger" onclick={() => (suspendModal = { reason: '' })} disabled={actionLoading}>suspend</button>
          {/if}
        {:else}
          <span class="muted">No actions available for retired accounts.</span>
        {/if}
      </div>
    </section>
  {/if}

  {#if tierModal}
    <div class="modal-backdrop" onclick={() => (tierModal = null)}></div>
    <div class="tier-modal">
      <h2>{tierModal.action === 'promote' ? 'Promote' : 'Demote'} account</h2>
      <p class="mono">{accountId}</p>

      <label>
        Target tier
        <select bind:value={tierModal.targetTier}>
          {#if tierModal.action === 'promote'}
            <option value={1}>T1 authenticated</option>
            <option value={2}>T2 trusted</option>
            <option value={3}>T3 vetted</option>
          {:else}
            <option value={0}>T0 anonymous</option>
            <option value={1}>T1 authenticated</option>
            <option value={2}>T2 trusted</option>
          {/if}
        </select>
      </label>

      <label>
        Reason (required)
        <textarea bind:value={tierModal.reason} rows="3" placeholder="Why is this tier change justified? (e.g., identity verified via institutional email, vouched by T2+ volunteer, hardware fault investigation)"></textarea>
      </label>

      <div class="modal-actions">
        <button onclick={() => (tierModal = null)}>cancel</button>
        <button class="primary" onclick={submitTierChange} disabled={actionLoading || !tierModal.reason.trim()}>
          {tierModal.action} to {tierNames[tierModal.targetTier] ?? `T${tierModal.targetTier}`}
        </button>
      </div>
    </div>
  {/if}

  {#if suspendModal}
    <div class="modal-backdrop" onclick={() => (suspendModal = null)}></div>
    <div class="tier-modal">
      <h2>Suspend account</h2>
      <p class="mono">{accountId}</p>
      <p class="warn-text">This will quarantine all workers bound to this account.</p>

      <label>
        Reason (required)
        <textarea bind:value={suspendModal.reason} rows="3" placeholder="Why is this account being suspended? (e.g., deliberate result manipulation, Sybil behavior, Terms of Participation violation)"></textarea>
      </label>

      <div class="modal-actions">
        <button onclick={() => (suspendModal = null)}>cancel</button>
        <button class="danger" onclick={submitSuspend} disabled={actionLoading || !suspendModal.reason.trim()}>
          suspend account
        </button>
      </div>
    </div>
  {/if}

  {#if unsuspendModal}
    <div class="modal-backdrop" onclick={() => (unsuspendModal = null)}></div>
    <div class="tier-modal">
      <h2>Unsuspend account</h2>
      <p class="mono">{accountId}</p>
      <p class="muted">This will unquarantine all workers bound to this account.</p>

      <label>
        Reason (required)
        <textarea bind:value={unsuspendModal.reason} rows="3" placeholder="Why is this suspension being lifted? (e.g., investigation concluded, false positive, remediation confirmed)"></textarea>
      </label>

      <div class="modal-actions">
        <button onclick={() => (unsuspendModal = null)}>cancel</button>
        <button class="primary" onclick={submitUnsuspend} disabled={actionLoading || !unsuspendModal.reason.trim()}>
          unsuspend account
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
  .suspended-badge { background: #7f1d1d; color: #fca5a5; }
  .retired-badge { background: #374151; color: #6b7280; }
  .quarantine-badge { background: #7f1d1d; color: #fca5a5; }
  .stale-badge { background: #78350f; color: #fbbf24; }
  .idp-badge { background: #1e3a5f; color: #93c5fd; }
  .badge.tier-0 { background: #1f2937; }
  .badge.tier-1 { background: #1e3a5f; color: #93c5fd; }
  .badge.tier-2 { background: #14532d; color: #86efac; }
  .badge.tier-3 { background: #4c1d95; color: #c4b5fd; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  .id-link { color: #a78bfa; text-decoration: none; }
  .id-link:hover { text-decoration: underline; }
  .tenant-block { padding: 0.5em 0.25em 0.6em; }
  .tenant-block + .tenant-block { border-top: 1px solid #1a1e2a; }
  .tenant-head { display: flex; align-items: center; gap: 0.5em; flex-wrap: wrap; }
  .tenant-id { color: #c4b5fd; }
  .tenant-name { color: #d4d4dc; }
  .tenant-badge { background: #312e81; color: #c4b5fd; }
  .tenant-facts { display: grid; grid-template-columns: 10em 1fr; gap: 0.2em 1em; margin: 0.4em 0 0; font-size: 0.9em; }
  .tenant-facts dt { color: #6b7280; font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.06em; }
  .tenant-facts dd { margin: 0; }
  .pending-line { margin: 0.75em 0 0; }
  .pending-chip { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #78350f; color: #fcd34d; text-decoration: none; }
  .pending-chip:hover { background: #92400e; }
  .inner-table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
  .inner-table th { text-align: left; padding: 0.5em; border-bottom: 2px solid #2a2e3a; color: #9ca3af; font-weight: 500; }
  .inner-table td { padding: 0.5em; border-bottom: 1px solid #1a1e2a; }
  .action-row { display: flex; gap: 0.5em; flex-wrap: wrap; align-items: center; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.35em 0.75em; border-radius: 4px; cursor: pointer; font: inherit; font-size: 0.85em; }
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
  .tier-modal select, .tier-modal textarea { width: 100%; padding: 0.4em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; font-size: 0.9em; resize: vertical; }
  .tier-modal textarea:focus { outline: none; border-color: #a78bfa; }
  .modal-actions { display: flex; gap: 0.75em; justify-content: flex-end; margin-top: 1.25em; }
  .warn-text { color: #fbbf24; font-size: 0.9em; margin: 0.25em 0 0.5em; }
</style>
