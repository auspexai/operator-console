<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';

  type Tenant = {
    tenant_id: string;
    display_name: string | null;
    description: string | null;
    contact_public: string | null;
    registered_at: string | null;
    revision: number | null;
    // operator sees these too (filtered in for the maintainer credential)
    contact_email: string | null;
    maintainer_pubkey: string | null;
  };

  type LinkedAccount = {
    account_id: string;
    idp: string;
    display_name: string | null;
    trust_tier: number;
    created_at: string | null;
    suspended_at: string | null;
  };

  type LinkedWorker = {
    worker_id: string;
    pubkey_hex: string;
    trust_tier: number;
    last_heartbeat_at: string | null;
    retired_at: string | null;
    quarantined_at: string | null;
  };

  type Linkage = {
    tenant_id: string;
    display_name: string | null;
    maintainer_pubkey: string | null;
    account_id: string | null;
    account: LinkedAccount | null;
    workers: LinkedWorker[];
  };

  const tierNames: Record<number, string> = {
    0: 'T0 anonymous',
    1: 'T1 authenticated',
    2: 'T2 trusted',
    3: 'T3 vetted',
  };

  let tenants = $state<Tenant[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  // tenant_id → linkage (lazy-loaded on expand). `null` = loading; a string key
  // absent = not yet expanded.
  let linkages = $state<Record<string, Linkage | null>>({});
  let linkageErrors = $state<Record<string, string>>({});
  let expanded = $state<Record<string, boolean>>({});

  async function loadTenants() {
    loading = true;
    error = null;
    try {
      const r = await fetch('/api/v0/proxy/tenants');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      tenants = body.tenants || body || [];
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  async function toggle(tenantId: string) {
    expanded[tenantId] = !expanded[tenantId];
    // Lazy-load the linkage the first time a tenant is expanded.
    if (expanded[tenantId] && linkages[tenantId] === undefined) {
      linkages[tenantId] = null; // loading marker
      delete linkageErrors[tenantId];
      try {
        const r = await fetch(`/api/v0/proxy/tenants/${tenantId}/linkage`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const body: Linkage = await r.json();
        body.workers = body.workers ?? [];
        linkages[tenantId] = body;
      } catch (e) {
        linkageErrors[tenantId] = (e as Error).message;
        delete linkages[tenantId];
      }
    }
  }

  const fmt = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : '—');
  const short = (hex: string | null | undefined) => (hex ? `${hex.slice(0, 16)}…` : '—');

  onMount(loadTenants);
</script>

<svelte:head>
  <title>Tenants — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> tenants</h1>
  </header>
  <Nav />

  {#if loading}
    <p class="muted">Loading tenants…</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else if tenants.length === 0}
    <p class="muted">No tenants registered.</p>
  {:else}
    <table>
      <thead>
        <tr>
          <th></th>
          <th>tenant_id</th>
          <th>display name</th>
          <th>contact</th>
          <th>registered</th>
        </tr>
      </thead>
      <tbody>
        {#each tenants as t (t.tenant_id)}
          <tr class="tenant-row" onclick={() => toggle(t.tenant_id)}>
            <td class="caret">{expanded[t.tenant_id] ? '▾' : '▸'}</td>
            <td class="mono">{t.tenant_id}</td>
            <td>{t.display_name ?? '—'}</td>
            <td class="muted">{t.contact_email ?? t.contact_public ?? '—'}</td>
            <td class="mono">{t.registered_at ? new Date(t.registered_at).toLocaleDateString() : '—'}</td>
          </tr>
          {#if expanded[t.tenant_id]}
            <tr class="linkage-row">
              <td></td>
              <td colspan="4">
                {#if linkageErrors[t.tenant_id]}
                  <p class="errortext">Failed to load linkage: {linkageErrors[t.tenant_id]}</p>
                {:else if linkages[t.tenant_id] === null || linkages[t.tenant_id] === undefined}
                  <p class="muted">Loading linkage…</p>
                {:else}
                  {@const lk = linkages[t.tenant_id]!}
                  <div class="linkage">
                    <div class="seg">
                      <span class="seg-label">maintainer pubkey</span>
                      <span class="mono">{short(lk.maintainer_pubkey)}</span>
                    </div>

                    {#if !lk.account}
                      <p class="muted unlinked">
                        Not linked to an account — no worker association.
                        {#if lk.account_id}
                          <span class="warn-text">(dangling account_id {lk.account_id})</span>
                        {/if}
                      </p>
                    {:else}
                      <div class="seg">
                        <span class="seg-label">account</span>
                        <span class="mono"><a href="/accounts/{lk.account.account_id}" class="id-link">{lk.account.account_id}</a></span>
                        <span class="badge idp-badge">{lk.account.idp}</span>
                        <span class="badge tier-{lk.account.trust_tier}">{tierNames[lk.account.trust_tier] ?? `T${lk.account.trust_tier}`}</span>
                        {#if lk.account.suspended_at}<span class="badge suspended-badge">suspended</span>{/if}
                      </div>

                      <span class="seg-label">workers ({lk.workers.length})</span>
                      {#if lk.workers.length === 0}
                        <p class="muted">No workers bound to this account yet.</p>
                      {:else}
                        <table class="workers">
                          <thead>
                            <tr><th>worker_id</th><th>pubkey</th><th>tier</th><th>last heartbeat</th><th>status</th></tr>
                          </thead>
                          <tbody>
                            {#each lk.workers as w (w.worker_id)}
                              <tr class:retired={!!w.retired_at} class:quarantined={!!w.quarantined_at}>
                                <td class="mono">{w.worker_id}</td>
                                <td class="mono">{short(w.pubkey_hex)}</td>
                                <td><span class="badge tier-{w.trust_tier}">{tierNames[w.trust_tier] ?? `T${w.trust_tier}`}</span></td>
                                <td class="mono">{fmt(w.last_heartbeat_at)}</td>
                                <td>
                                  {#if w.retired_at}
                                    <span class="badge retired-badge">retired</span>
                                  {:else if w.quarantined_at}
                                    <span class="badge quarantine-badge">quarantined</span>
                                  {:else}
                                    <span class="badge ok">active</span>
                                  {/if}
                                </td>
                              </tr>
                            {/each}
                          </tbody>
                        </table>
                      {/if}
                    {/if}
                  </div>
                {/if}
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
    <p class="muted">{tenants.length} tenant(s)</p>
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
  tr.tenant-row { cursor: pointer; }
  tr.tenant-row:hover { background: #161b28; }
  td.caret { width: 1.5em; color: #6b7280; }
  tr.linkage-row td { background: #0d1119; border-bottom: 1px solid #1a1e2a; }
  .linkage { padding: 0.5em 0.25em 0.75em; }
  .seg { display: flex; align-items: center; gap: 0.5em; margin: 0.35em 0; }
  .seg-label { display: inline-block; font-size: 0.7em; text-transform: uppercase; letter-spacing: 0.06em; color: #6b7280; }
  .unlinked { margin: 0.5em 0; }
  table.workers { margin-top: 0.4em; }
  table.workers th { font-size: 0.85em; border-bottom: 1px solid #2a2e3a; }
  table.workers tr.retired { opacity: 0.5; }
  table.workers tr.quarantined { background: rgba(127, 29, 29, 0.15); }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.ok { background: #14532d; color: #86efac; }
  .quarantine-badge { background: #7f1d1d; color: #fca5a5; }
  .suspended-badge { background: #7f1d1d; color: #fca5a5; }
  .retired-badge { background: #374151; color: #6b7280; }
  .idp-badge { background: #1e3a5f; color: #93c5fd; }
  .badge.tier-0 { background: #1f2937; }
  .badge.tier-1 { background: #1e3a5f; color: #93c5fd; }
  .badge.tier-2 { background: #14532d; color: #86efac; }
  .badge.tier-3 { background: #4c1d95; color: #c4b5fd; }
  .id-link { color: #a78bfa; text-decoration: none; }
  .id-link:hover { text-decoration: underline; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .warn-text { color: #fbbf24; }
  .errortext { color: #fca5a5; }
</style>
