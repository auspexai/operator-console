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
  };

  const tierNames: Record<number, string> = {
    0: 'T0 anonymous',
    1: 'T1 authenticated',
    2: 'T2 trusted',
    3: 'T3 vetted',
  };

  let accounts = $state<Account[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let actionLoading = $state(false);
  let live = $state(false);

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
    loadAccounts().then((ok) => (live = ok));
    // Poll is the truth, the SSE doorbell is a hint (M8 principle). The baseline
    // poll keeps tier/status current; receipt.issued nudges sooner because it can
    // auto-promote an account (T1→T2) in the background, shifting the tier badge.
    return autoRefresh({
      refresh: () => loadAccounts(true),
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
    <table>
      <thead>
        <tr>
          <th>account_id</th>
          <th>identity</th>
          <th>tier</th>
          <th>created</th>
          <th>status</th>
          <th>actions</th>
        </tr>
      </thead>
      <tbody>
        {#each accounts as acct}
          <tr class:suspended={!!acct.suspended_at} class:retired={!!acct.retired_at}>
            <td class="mono"><a href="/accounts/{acct.account_id}" class="id-link">{acct.account_id}</a></td>
            <td>
              <span class="badge idp-badge">{acct.idp}</span>
              {acct.display_name || acct.idp_sub}
            </td>
            <td><span class="badge tier-{acct.trust_tier}">{tierNames[acct.trust_tier] ?? `T${acct.trust_tier}`}</span></td>
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
        {/each}
      </tbody>
    </table>
    <p class="muted">{accounts.length} account(s)</p>
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
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  .id-link { color: #a78bfa; text-decoration: none; }
  .id-link:hover { text-decoration: underline; }
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
  .tier-modal select, .tier-modal textarea { width: 100%; padding: 0.4em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; font-size: 0.9em; resize: vertical; }
  .tier-modal textarea:focus { outline: none; border-color: #a78bfa; }
  .modal-actions { display: flex; gap: 0.75em; justify-content: flex-end; margin-top: 1.25em; }
  .warn-text { color: #fbbf24; font-size: 0.9em; margin: 0.25em 0 0.5em; }
</style>
