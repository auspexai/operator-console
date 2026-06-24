<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';
  import { autoRefresh } from '$lib/live';
  import LiveDot from '$lib/components/LiveDot.svelte';

  // The network model catalog — the bottom-up aggregate of what active workers
  // hold (the realized slice of the fleet-capability envelope, E8). The BYOM
  // model-request queue was retired 2026-06-24: researcher demand (model +
  // capability requests) now flows through GitHub Discussions, not an in-app
  // coordinator queue. Worker eligibility lives on /workers.

  type CatalogEntry = { model_id: string; worker_count: number };

  let catalog = $state<CatalogEntry[]>([]);
  let catalogTotal = $state(0);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let live = $state(false);

  async function loadAll(silent = false): Promise<boolean> {
    if (!silent) loading = true;
    try {
      const catR = await fetch('/api/v0/proxy/models/catalog');
      if (!catR.ok) throw new Error(`models/catalog HTTP ${catR.status}`);
      const c = await catR.json();
      catalog = c.models || [];
      catalogTotal = c.total_active_workers ?? 0;
      error = null;
      return true;
    } catch (e) {
      if (!silent) error = (e as Error).message;
      return false;
    } finally {
      if (!silent) loading = false;
    }
  }

  onMount(() => {
    loadAll().then((ok) => (live = ok));
    return autoRefresh({
      refresh: () => loadAll(true),
      setLive: (v) => (live = v),
      types: ['worker.status', 'network.status'],
    });
  });
</script>

<svelte:head>
  <title>Models — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1>
      <a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> models
      {#if !loading}<LiveDot {live} />{/if}
    </h1>
  </header>
  <Nav />

  {#if loading}
    <p class="muted">Loading models…</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else}
    <h2 class="section">Network model catalog</h2>
    <p class="muted">
      What the fleet can run — the bottom-up aggregate of models active workers hold
      ({catalogTotal} worker{catalogTotal === 1 ? '' : 's'}). Model &amp; capability requests are
      handled on
      <a href="https://github.com/auspexai/.github/discussions" target="_blank" rel="noopener">GitHub Discussions</a>.
    </p>
    {#if catalog.length === 0}
      <p class="muted">No models available on the network.</p>
    {:else}
      <table>
        <thead><tr><th>model_id</th><th>workers holding it</th></tr></thead>
        <tbody>
          {#each catalog as m (m.model_id)}
            <tr><td class="mono">{m.model_id}</td><td>{m.worker_count}</td></tr>
          {/each}
        </tbody>
      </table>
    {/if}
  {/if}
</main>

<style>
  main { max-width: 1100px; margin: 0 auto; padding: 2em 1.25em; }
  header { border-bottom: 1px solid #2a2e3a; padding-bottom: 0.75em; margin-bottom: 1.5em; }
  h1 { margin: 0; font-size: 1.5em; font-weight: 600; color: #fff; }
  h2.section { margin: 1.75em 0 0.25em; font-size: 1.1em; font-weight: 600; color: #d4d4dc; border-bottom: 1px solid #2a2e3a; padding-bottom: 0.3em; }
  .brand { color: #a78bfa; }
  .brand-link { text-decoration: none; color: inherit; }
  a { color: #a78bfa; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
  th { text-align: left; padding: 0.5em; border-bottom: 2px solid #2a2e3a; color: #9ca3af; font-weight: 500; }
  td { padding: 0.5em; border-bottom: 1px solid #1a1e2a; vertical-align: top; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
</style>
