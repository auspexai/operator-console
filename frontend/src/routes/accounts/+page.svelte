<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';
  import LiveDot from '$lib/components/LiveDot.svelte';
  import { autoRefresh } from '$lib/live';

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
    // Per-account T1→T2 promotion readiness (present only for T1 accounts): so a
    // maintainer sees who's EARNED it at a glance, not post-hoc via gate-override.
    t2_readiness: {
      receipts: number;
      receipts_required: number;
      distinct_experiments: number;
      distinct_required: number;
      identity_satisfied: boolean;
      ready: boolean;
    } | null;
    // Research standing (0=R0…3=R3) + per-account R1→R2 review readiness (present
    // only for R1 accounts, the promotable research tier): so a maintainer sees
    // who's EARNED an R2 review at a glance, mirroring t2_readiness for trust tier.
    research_standing: number;
    r2_readiness: { distinct: number; threshold: number; ready: boolean } | null;
  };

  // Full tenant facts (the former standalone /tenants page collapsed into this
  // page — account = the root, one home per fact). The operator credential sees
  // contact_email + maintainer_pubkey in the tenants LIST response.
  type Tenant = {
    tenant_id: string;
    display_name: string | null;
    description: string | null;
    contact_public: string | null;
    contact_email: string | null;
    registered_at: string | null;
    maintainer_pubkey: string | null;
  };

  type TenantEntry = Tenant & {
    account_id: string | null;
    // false = the per-tenant linkage fetch failed, so the account binding is
    // UNKNOWN (don't assert "no account").
    linkage_ok: boolean;
  };

  const tierNames: Record<number, string> = {
    0: 'T0 anonymous',
    1: 'T1 authenticated',
    2: 'T2 trusted',
    3: 'T3 vetted',
  };

  // Friendly research-standing labels (mirrors the account detail page); fall
  // back to the raw level for forward-compat.
  const standingLabels: Record<number, string> = {
    0: 'R0 · unverified',
    1: 'R1 · verified',
    2: 'R2 · established',
    3: 'R3 · trusted',
  };
  const standingLabel = (level: number) => standingLabels[level] ?? `R${level}`;

  let accounts = $state<Account[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let actionLoading = $state(false);
  let live = $state(false);

  // Tenant directory, nested under accounts. The tenants LIST response carries
  // no account_id (operator-only field, exposed via the per-tenant linkage
  // endpoint), so join client-side: list tenants, fetch each tenant's linkage,
  // and bucket the full tenant facts by account_id. Tenant count is small, so
  // the fan-out is cheap. Best-effort enrichment: on failure render no tenants
  // rather than failing the page (matching the detail page's
  // receipt-stats/workers degrade).
  let tenantDirectory = $state<TenantEntry[]>([]);
  let pendingAppsByAccount = $state<Record<string, number>>({});

  const knownAccountIds = $derived(new Set(accounts.map((a) => a.account_id)));
  // Glance-level: how many loaded accounts are eligible for an R1→R2 review, so a
  // maintainer notices without scanning every row.
  const r2ReadyCount = $derived(accounts.filter((a) => a.r2_readiness?.ready).length);
  const tenantsByAccount = $derived.by(() => {
    const byAccount: Record<string, TenantEntry[]> = {};
    for (const t of tenantDirectory) {
      if (t.account_id && knownAccountIds.has(t.account_id)) (byAccount[t.account_id] ??= []).push(t);
    }
    return byAccount;
  });
  // No account_id (legacy hand-created tenants), a dangling account_id, or an
  // unknown binding — all land in the bottom "Unlinked tenants" section so
  // every registered tenant has exactly one home on this page.
  const unlinkedTenants = $derived(
    tenantDirectory.filter((t) => !t.account_id || !knownAccountIds.has(t.account_id)),
  );

  async function loadLinkages(): Promise<void> {
    try {
      const [tenantsRes, appsRes] = await Promise.all([
        fetch('/api/v0/proxy/tenants'),
        fetch('/api/v0/proxy/tenant-applications'),
      ]);

      if (tenantsRes.ok) {
        const body = await tenantsRes.json();
        const tenants: Tenant[] = body.tenants || body || [];
        tenantDirectory = await Promise.all(
          tenants.map(async (t): Promise<TenantEntry> => {
            try {
              const r = await fetch(`/api/v0/proxy/tenants/${encodeURIComponent(t.tenant_id)}/linkage`);
              if (!r.ok) throw new Error(`HTTP ${r.status}`);
              const lk = (await r.json()) as { account_id?: string | null };
              return { ...t, account_id: lk.account_id ?? null, linkage_ok: true };
            } catch {
              return { ...t, account_id: null, linkage_ok: false };
            }
          }),
        );
      }

      // Section-level degrade: a coordinator without the tenant-applications
      // routes yet shouldn't take down the tenant chips (or the page).
      if (appsRes.ok) {
        const apps: { account_id?: string; status?: string }[] = (await appsRes.json()).applications || [];
        const counts: Record<string, number> = {};
        for (const a of apps) {
          if (a.status === 'pending' && a.account_id) counts[a.account_id] = (counts[a.account_id] ?? 0) + 1;
        }
        pendingAppsByAccount = counts;
      }
    } catch {
      /* best-effort enrichment — keep whatever rendered last */
    }
  }

  // The full visible surface: the accounts list + the account→tenant linkage
  // overlay. Liveness tracks the accounts list (the linkage is best-effort).
  async function refreshAll(silent = false): Promise<boolean> {
    const [ok] = await Promise.all([loadAccounts(silent), loadLinkages()]);
    return ok;
  }

  const shortHex = (hex: string | null | undefined) => (hex ? `${hex.slice(0, 16)}…` : '—');

  let tierModal = $state<{
    accountId: string;
    action: 'promote' | 'demote';
    targetTier: number;
    reason: string;
  } | null>(null);

  async function loadAccounts(silent = false): Promise<boolean> {
    if (!silent) loading = true;
    try {
      const r = await fetch('/api/v0/proxy/accounts');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      accounts = body.accounts || body || [];
      error = null;
      return true;
    } catch (e) {
      if (!silent) error = (e as Error).message;
      return false;
    } finally {
      if (!silent) loading = false;
    }
  }

  function showTierModal(accountId: string, action: 'promote' | 'demote', currentTier: number) {
    tierModal = {
      accountId,
      action,
      targetTier: action === 'promote' ? Math.min(currentTier + 1, 3) : Math.max(currentTier - 1, 0),
      reason: '',
    };
  }

  async function submitTierChange() {
    if (!tierModal) return;
    actionLoading = true;
    try {
      const r = await fetch(`/api/v0/proxy/accounts/${tierModal.accountId}/actions/${tierModal.action}`, {
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
      await loadAccounts();
    } catch (e) {
      alert(`${tierModal?.action} failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  // Link an EXISTING (unlinked) tenant to an account — the post-registration
  // linkage that the trust model (tier floor, own-worker enrichment, promotion)
  // depends on.
  let linkModal = $state<{ tenantId: string; accountId: string; reason: string } | null>(null);

  function showLinkModal(tenantId: string) {
    linkModal = { tenantId, accountId: accounts[0]?.account_id ?? '', reason: '' };
  }

  async function submitLink() {
    if (!linkModal || !linkModal.accountId) return;
    actionLoading = true;
    try {
      const r = await fetch(
        `/api/v0/proxy/tenants/${encodeURIComponent(linkModal.tenantId)}/actions/link`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ account_id: linkModal.accountId, reason: linkModal.reason }),
        },
      );
      if (!r.ok) {
        const d = await r.json();
        throw new Error(JSON.stringify(d));
      }
      linkModal = null;
      await refreshAll(true);
    } catch (e) {
      alert(`link failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  let suspendModal = $state<{ accountId: string; reason: string } | null>(null);

  async function submitSuspend() {
    if (!suspendModal) return;
    actionLoading = true;
    try {
      const r = await fetch(`/api/v0/proxy/accounts/${suspendModal.accountId}/actions/suspend`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: suspendModal.reason }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      suspendModal = null;
      await loadAccounts();
    } catch (e) {
      alert(`Suspend failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  let unsuspendModal = $state<{ accountId: string; reason: string } | null>(null);

  async function submitUnsuspend() {
    if (!unsuspendModal) return;
    actionLoading = true;
    try {
      const r = await fetch(`/api/v0/proxy/accounts/${unsuspendModal.accountId}/actions/unsuspend`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: unsuspendModal.reason }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      unsuspendModal = null;
      await loadAccounts();
    } catch (e) {
      alert(`Unsuspend failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }

  onMount(() => {
    refreshAll().then((ok) => (live = ok));
    // Poll is the truth, the SSE doorbell is a hint (M8 principle). The baseline
    // poll keeps tier/status current; receipt.issued nudges sooner because it can
    // auto-promote an account (T1→T2) in the background, shifting the tier badge.
    return autoRefresh({
      refresh: () => refreshAll(true),
      setLive: (v) => (live = v),
      types: ['receipt.issued'],
    });
  });
</script>

<svelte:head>
  <title>Accounts — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> accounts
      {#if !loading}<LiveDot {live} />{/if}
    </h1>
  </header>
  <Nav />

  {#if loading}
    <p class="muted">Loading accounts...</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else if accounts.length === 0}
    <p class="muted">No accounts registered.</p>
  {:else}
    {#if r2ReadyCount > 0}
      <p class="r2-ready-summary">{r2ReadyCount} account{r2ReadyCount === 1 ? '' : 's'} eligible for R2 review</p>
    {/if}
    <table>
      <thead>
        <tr>
          <th>account_id</th>
          <th>identity</th>
          <th>tier</th>
          <th>tenants</th>
          <th>created</th>
          <th>status</th>
          <th>actions</th>
        </tr>
      </thead>
      <tbody>
        {#each accounts as acct (acct.account_id)}
          <tr class:suspended={!!acct.suspended_at} class:retired={!!acct.retired_at}>
            <td class="mono"><a href="/accounts/{acct.account_id}" class="id-link">{acct.account_id}</a></td>
            <td>
              <span class="badge idp-badge">{acct.idp}</span>
              {acct.display_name || acct.idp_sub}
            </td>
            <td>
              <span class="badge tier-{acct.trust_tier}">{tierNames[acct.trust_tier] ?? `T${acct.trust_tier}`}</span>
              <span class="badge standing-{acct.research_standing}" title="Research standing">{standingLabel(acct.research_standing)}</span>
              {#if acct.t2_readiness}
                <div class="t2-ready" title="Progress toward T1→T2 promotion (receipts + distinct experiments + identity gate).">
                  {#if acct.t2_readiness.ready}<span class="ready-badge">ready for T2</span>{/if}
                  <span class="rd" class:met={acct.t2_readiness.receipts >= acct.t2_readiness.receipts_required}>{acct.t2_readiness.receipts}/{acct.t2_readiness.receipts_required} receipts</span>
                  <span class="rd" class:met={acct.t2_readiness.distinct_experiments >= acct.t2_readiness.distinct_required}>{acct.t2_readiness.distinct_experiments}/{acct.t2_readiness.distinct_required} exps</span>
                  <span class="rd" class:met={acct.t2_readiness.identity_satisfied}>{acct.t2_readiness.identity_satisfied ? 'identity ✓' : 'identity pending'}</span>
                </div>
              {/if}
              {#if acct.r2_readiness}
                <div class="t2-ready" title="Progress toward R1→R2 review (distinct completed + attested experiments).">
                  {#if acct.r2_readiness.ready}<span class="ready-badge">ready for R2 review</span>{/if}
                  <span class="rd" class:met={acct.r2_readiness.distinct >= acct.r2_readiness.threshold}>{acct.r2_readiness.distinct}/{acct.r2_readiness.threshold} exps</span>
                </div>
              {/if}
            </td>
            <td class="linkage-cell">
              <!-- Empty for most volunteers — only researcher accounts carry tenants/applications.
                   Tenant facts render nested below the row (the former /tenants page's home). -->
              {#if (tenantsByAccount[acct.account_id] ?? []).length > 0}
                <span class="muted">{tenantsByAccount[acct.account_id].length} tenant{tenantsByAccount[acct.account_id].length === 1 ? '' : 's'} ↓</span>
              {/if}
              {#if pendingAppsByAccount[acct.account_id]}
                <a href="/requests" class="pending-chip" title="pending tenant application(s) — review on the requests page">{pendingAppsByAccount[acct.account_id]} pending app{pendingAppsByAccount[acct.account_id] === 1 ? '' : 's'}</a>
              {/if}
            </td>
            <td class="mono">{new Date(acct.created_at).toLocaleDateString()}</td>
            <td>
              {#if acct.retired_at}
                <span class="badge retired-badge">retired</span>
              {:else if acct.suspended_at}
                <span class="badge suspended-badge">suspended</span>
                {#if acct.suspension_reason}
                  <span class="muted"> — {acct.suspension_reason}</span>
                {/if}
              {:else}
                <span class="badge ok">active</span>
              {/if}
            </td>
            <td class="actions">
              {#if !acct.retired_at}
                {#if acct.trust_tier < 3}
                  <button onclick={() => showTierModal(acct.account_id, 'promote', acct.trust_tier)} disabled={actionLoading}>promote</button>
                {/if}
                {#if acct.trust_tier > 0}
                  <button onclick={() => showTierModal(acct.account_id, 'demote', acct.trust_tier)} disabled={actionLoading}>demote</button>
                {/if}
                {#if acct.suspended_at}
                  <button onclick={() => (unsuspendModal = { accountId: acct.account_id, reason: '' })} disabled={actionLoading}>unsuspend</button>
                {:else}
                  <button class="danger" onclick={() => (suspendModal = { accountId: acct.account_id, reason: '' })} disabled={actionLoading}>suspend</button>
                {/if}
              {/if}
            </td>
          </tr>
          {#if (tenantsByAccount[acct.account_id] ?? []).length > 0}
            <!-- Tenants nest under their account (one home per fact: account =
                 the root). Full tenant facts, formerly the /tenants page. -->
            <tr class="tenant-nest-row">
              <td class="nest-indent" aria-hidden="true"></td>
              <td colspan="6">
                {#each tenantsByAccount[acct.account_id] as t (t.tenant_id)}
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
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
    <p class="muted">{accounts.length} account(s)</p>
  {/if}

  <!-- Tenants with NO account binding (legacy hand-created registrations) —
       rendered even when the accounts list itself is empty, so every
       registered tenant keeps a home on this page. -->
  {#if !loading && !error && unlinkedTenants.length > 0}
    <section class="unlinked-section">
      <h2>Unlinked tenants</h2>
      <p class="muted">Registered tenants with no linked account (legacy hand-created) — no worker association.</p>
      {#each unlinkedTenants as t (t.tenant_id)}
        <div class="tenant-block">
          <div class="tenant-head">
            <span class="badge tenant-badge">tenant</span>
            <span class="mono tenant-id">{t.tenant_id}</span>
            {#if t.display_name}<span class="tenant-name">{t.display_name}</span>{/if}
            {#if !t.linkage_ok}
              <span class="warn-text">account linkage unavailable</span>
            {:else if t.account_id}
              <span class="warn-text">dangling account_id {t.account_id} (no matching account)</span>
            {:else}
              <span class="badge no-account-badge">no account</span>
            {/if}
          </div>
          <dl class="tenant-facts">
            <dt>contact</dt><dd>{t.contact_email ?? t.contact_public ?? '—'}</dd>
            <dt>registered</dt><dd class="mono">{t.registered_at ? new Date(t.registered_at).toLocaleString() : '—'}</dd>
            <dt>maintainer pubkey</dt><dd class="mono" title={t.maintainer_pubkey ?? undefined}>{shortHex(t.maintainer_pubkey)}</dd>
            {#if t.description}<dt>description</dt><dd>{t.description}</dd>{/if}
          </dl>
          {#if accounts.length > 0}
            <button class="link-btn" onclick={() => showLinkModal(t.tenant_id)} disabled={actionLoading}>link to account…</button>
          {/if}
        </div>
      {/each}
    </section>
  {/if}

  {#if tierModal}
    <div class="modal-backdrop" onclick={() => (tierModal = null)}></div>
    <div class="tier-modal">
      <h2>{tierModal.action === 'promote' ? 'Promote' : 'Demote'} account</h2>
      <p class="mono">{tierModal.accountId}</p>

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

  {#if linkModal}
    <div class="modal-backdrop" onclick={() => (linkModal = null)}></div>
    <div class="tier-modal">
      <h2>Link tenant to account</h2>
      <p class="mono">{linkModal.tenantId}</p>
      <label>
        Account
        <select bind:value={linkModal.accountId}>
          {#each accounts as a (a.account_id)}
            <option value={a.account_id}
              >{a.account_id} ({tierNames[a.trust_tier] ?? `T${a.trust_tier}`}) — {a.display_name ||
                a.idp_sub}</option
            >
          {/each}
        </select>
      </label>
      <label>
        Reason (required)
        <textarea bind:value={linkModal.reason} rows="3" placeholder="Why link this tenant to this account? (e.g., onboarding the operator's research tenant so the account's tier governs its experiments)"></textarea>
      </label>
      <div class="modal-actions">
        <button onclick={() => (linkModal = null)}>cancel</button>
        <button class="primary" onclick={submitLink} disabled={actionLoading || !linkModal.accountId || !linkModal.reason.trim()}>link</button>
      </div>
    </div>
  {/if}

  {#if suspendModal}
    <div class="modal-backdrop" onclick={() => (suspendModal = null)}></div>
    <div class="tier-modal">
      <h2>Suspend account</h2>
      <p class="mono">{suspendModal.accountId}</p>
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
      <p class="mono">{unsuspendModal.accountId}</p>
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
  .brand { color: #a78bfa; }
  .brand-link { text-decoration: none; color: inherit; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
  th { text-align: left; padding: 0.5em; border-bottom: 2px solid #2a2e3a; color: #9ca3af; font-weight: 500; }
  td { padding: 0.5em; border-bottom: 1px solid #1a1e2a; }
  tr.suspended { background: rgba(127, 29, 29, 0.15); }
  tr.retired { opacity: 0.5; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.ok { background: #14532d; color: #86efac; }
  .suspended-badge { background: #7f1d1d; color: #fca5a5; }
  .retired-badge { background: #374151; color: #6b7280; }
  .idp-badge { background: #1e3a5f; color: #93c5fd; margin-right: 0.4em; }
  .badge.tier-0 { background: #1f2937; }
  .badge.tier-1 { background: #1e3a5f; color: #93c5fd; }
  .badge.tier-2 { background: #14532d; color: #86efac; }
  .badge.tier-3 { background: #4c1d95; color: #c4b5fd; }
  .badge.standing-0 { background: #1f2937; }
  .badge.standing-1 { background: #1e3a5f; color: #93c5fd; }
  .badge.standing-2 { background: #14532d; color: #86efac; }
  .badge.standing-3 { background: #4c1d95; color: #c4b5fd; }
  .r2-ready-summary { margin: 0 0 1em; padding: 0.4em 0.75em; display: inline-block; border-radius: 4px; font-size: 0.9em; font-weight: 600; background: #14532d; color: #86efac; border: 1px solid #22c55e; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  .id-link { color: #a78bfa; text-decoration: none; }
  .id-link:hover { text-decoration: underline; }
  /* T1→T2 promotion readiness (per-account, in the tier cell) */
  .t2-ready { margin-top: 0.35em; display: flex; flex-direction: column; gap: 0.12em; }
  .ready-badge { align-self: flex-start; padding: 0.05em 0.5em; border-radius: 3px; font-size: 0.78em; font-weight: 600; background: #14532d; color: #86efac; border: 1px solid #22c55e; }
  .rd { font-size: 0.78em; color: #9ca3af; font-variant-numeric: tabular-nums; }
  .rd.met { color: #6ee7a0; }
  .linkage-cell .pending-chip { margin-left: 0.3em; }
  .pending-chip { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #78350f; color: #fcd34d; text-decoration: none; }
  .pending-chip:hover { background: #92400e; }
  tr.tenant-nest-row td { background: #0d1119; border-bottom: 1px solid #1a1e2a; }
  td.nest-indent { width: 1.5em; }
  .tenant-block { padding: 0.5em 0.25em 0.6em; }
  .tenant-block + .tenant-block { border-top: 1px solid #1a1e2a; }
  .tenant-head { display: flex; align-items: center; gap: 0.5em; flex-wrap: wrap; }
  .tenant-id { color: #c4b5fd; }
  .tenant-name { color: #d4d4dc; }
  .tenant-badge { background: #312e81; color: #c4b5fd; }
  .no-account-badge { background: #78350f; color: #fcd34d; }
  .tenant-facts { display: grid; grid-template-columns: 10em 1fr; gap: 0.2em 1em; margin: 0.4em 0 0; font-size: 0.9em; }
  .tenant-facts dt { color: #6b7280; font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.06em; }
  .tenant-facts dd { margin: 0; }
  .unlinked-section { margin-top: 2em; }
  .unlinked-section h2 { font-size: 1.05em; font-weight: 600; color: #fff; margin: 0 0 0.25em; }
  .unlinked-section .tenant-block { background: #0d1119; border: 1px solid #1a1e2a; border-radius: 8px; padding: 0.6em 0.85em; margin: 0.5em 0; }
  .unlinked-section .tenant-block + .tenant-block { border-top: 1px solid #1a1e2a; }
  .actions { white-space: nowrap; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.25em 0.65em; border-radius: 4px; cursor: pointer; font: inherit; font-size: 0.85em; }
  button:hover { background: #2a2e3a; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  button.primary { background: #a78bfa; color: #0a0e1a; border-color: #a78bfa; font-weight: 600; }
  button.primary:hover { background: #c4b5fd; }
  button.danger { background: #7f1d1d; border-color: #7f1d1d; color: #fca5a5; }
  button.danger:hover { background: #991b1b; }
  .modal-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); z-index: 10; }
  .link-btn { margin-top: 0.6em; }
  .tier-modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #1a1e2a; border: 1px solid #2a2e3a; border-radius: 8px; padding: 1.5em; z-index: 11; width: 90%; max-width: 500px; }
  .tier-modal h2 { margin: 0 0 0.5em; color: #fff; font-size: 1.1em; }
  .tier-modal label { display: block; margin: 0.75em 0 0.25em; color: #9ca3af; font-size: 0.9em; }
  .tier-modal select, .tier-modal textarea { width: 100%; padding: 0.4em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; font-size: 0.9em; resize: vertical; }
  .tier-modal textarea:focus { outline: none; border-color: #a78bfa; }
  .modal-actions { display: flex; gap: 0.75em; justify-content: flex-end; margin-top: 1.25em; }
  .warn-text { color: #fbbf24; font-size: 0.9em; margin: 0.25em 0 0.5em; }
</style>
