<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';

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

  const tierNames: Record<number, string> = {
    0: 'T0 anonymous',
    1: 'T1 authenticated',
    2: 'T2 trusted',
    3: 'T3 vetted',
  };

  let workers = $state<Worker[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function loadWorkers() {
    loading = true;
    error = null;
    try {
      const r = await fetch('/api/v0/proxy/workers');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      workers = body.workers || body || [];
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  async function quarantine(workerId: string) {
    const reason = prompt('Quarantine reason (optional):');
    try {
      await fetch(`/api/v0/proxy/workers/${workerId}/actions/quarantine`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });
      await loadWorkers();
    } catch (e) {
      alert(`Failed: ${(e as Error).message}`);
    }
  }

  async function unquarantine(workerId: string) {
    try {
      await fetch(`/api/v0/proxy/workers/${workerId}/actions/unquarantine`, {
        method: 'POST',
      });
      await loadWorkers();
    } catch (e) {
      alert(`Failed: ${(e as Error).message}`);
    }
  }

  onMount(loadWorkers);
</script>

<svelte:head>
  <title>Workers — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> workers fleet</h1>
  </header>
  <Nav />

  {#if loading}
    <p class="muted">Loading workers…</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else if workers.length === 0}
    <p class="muted">No workers enrolled.</p>
  {:else}
    <table>
      <thead>
        <tr>
          <th>worker_id</th>
          <th>tier</th>
          <th>account</th>
          <th>last heartbeat</th>
          <th>status</th>
          <th>actions</th>
        </tr>
      </thead>
      <tbody>
        {#each workers as w}
          <tr class:quarantined={!!w.quarantined_at} class:retired={!!w.retired_at}>
            <td class="mono">{w.worker_id}</td>
            <td><span class="badge tier-{w.trust_tier}">{tierNames[w.trust_tier] ?? `T${w.trust_tier}`}</span></td>
            <td class="mono">{#if w.account_id}<a href="/accounts/{w.account_id}" class="id-link">{w.account_id}</a>{:else}—{/if}</td>
            <td class="mono">{w.last_heartbeat_at ? new Date(w.last_heartbeat_at).toLocaleString() : '—'}</td>
            <td>
              {#if w.retired_at}
                <span class="badge retired-badge">retired</span>
              {:else if w.quarantined_at}
                <span class="badge quarantine-badge">quarantined</span>
                {#if w.quarantine_reason}
                  <span class="muted"> — {w.quarantine_reason}</span>
                {/if}
              {:else if !w.last_heartbeat_at || (Date.now() - new Date(w.last_heartbeat_at).getTime()) > 180_000}
                <span class="badge stale-badge">offline</span>
              {:else}
                <span class="badge ok">active</span>
              {/if}
            </td>
            <td>
              {#if !w.retired_at}
                {#if w.quarantined_at}
                  <button onclick={() => unquarantine(w.worker_id)}>unquarantine</button>
                {:else}
                  <button onclick={() => quarantine(w.worker_id)}>quarantine</button>
                {/if}
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p class="muted">{workers.length} worker(s)</p>
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
  tr.quarantined { background: rgba(127, 29, 29, 0.15); }
  tr.retired { opacity: 0.5; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.ok { background: #14532d; color: #86efac; }
  .quarantine-badge { background: #7f1d1d; color: #fca5a5; }
  .retired-badge { background: #374151; color: #6b7280; }
  .stale-badge { background: #78350f; color: #fbbf24; }
  .badge.tier-0 { background: #1f2937; }
  .badge.tier-1 { background: #1e3a5f; color: #93c5fd; }
  .badge.tier-2 { background: #14532d; color: #86efac; }
  .badge.tier-3 { background: #4c1d95; color: #c4b5fd; }
  .id-link { color: #a78bfa; text-decoration: none; }
  .id-link:hover { text-decoration: underline; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.25em 0.65em; border-radius: 4px; cursor: pointer; font: inherit; font-size: 0.85em; }
  button:hover { background: #2a2e3a; }
</style>
