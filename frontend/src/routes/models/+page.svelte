<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';
  import { autoRefresh } from '$lib/live';
  import LiveDot from '$lib/components/LiveDot.svelte';

  // What the fleet can actually RUN — the /models/supported fit verdict, which sizes
  // each model by its real serve footprint (weights + KV cache + runtime) and honours
  // observed serve failures. This replaced a "workers holding it" count that read a
  // model PRESENT on a too-small worker's disk as if the fleet could run it there
  // (a 7B like mistral is prestaged to the Jetsons' disk but only the Mac can serve
  // it). Runs-on (fits) is the number that matters; held is disk presence only.

  type Entry = {
    model_id: string;
    status: string; // available | runnable | too_big | unknown
    approx_ram_gb: number | null;
    fits_worker_count?: number;
    on_worker_count?: number;
  };

  let models = $state<Entry[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let live = $state(false);

  const rank: Record<string, number> = { available: 0, runnable: 1, unknown: 2, too_big: 3 };

  async function loadAll(silent = false): Promise<boolean> {
    if (!silent) loading = true;
    try {
      const r = await fetch('/api/v0/proxy/models/supported');
      if (!r.ok) throw new Error(`models/supported HTTP ${r.status}`);
      const c = await r.json();
      models = ((c.models || []) as Entry[]).sort(
        (a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9) || a.model_id.localeCompare(b.model_id),
      );
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
    <h2 class="section">What the fleet can run</h2>
    <p class="muted">
      Sized by the real serve footprint (weights + KV cache + runtime), not just the file — a
      model too big to serve reads <span class="badge too_big">too_big</span> even if it's staged
      on a worker's disk. <strong>Runs on</strong> is how many workers can actually serve it;
      <strong>held</strong> is disk presence only. Model &amp; capability requests are handled on
      <a href="https://github.com/auspexai/.github/discussions" target="_blank" rel="noopener">GitHub Discussions</a>.
    </p>
    {#if models.length === 0}
      <p class="muted">No models on the network.</p>
    {:else}
      <table>
        <thead>
          <tr><th>model_id</th><th>status</th><th>serve ~GB</th><th>runs on</th><th>held</th></tr>
        </thead>
        <tbody>
          {#each models as m (m.model_id)}
            <tr>
              <td class="mono">{m.model_id}</td>
              <td><span class="badge {m.status}">{m.status}</span></td>
              <td class="num">{m.approx_ram_gb ?? '—'}</td>
              <td class="num" title="workers that can actually serve this model">
                {m.fits_worker_count ?? '—'}
              </td>
              <td class="num muted" title="workers holding the file on disk (not necessarily runnable)">
                {m.on_worker_count ?? 0}
              </td>
            </tr>
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
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.available { background: #14532d; color: #86efac; }
  .badge.runnable { background: #1e3a5f; color: #93c5fd; }
  .badge.too_big { background: #7f1d1d; color: #fca5a5; }
  .badge.unknown { background: #374151; color: #d4d4dc; }
</style>
