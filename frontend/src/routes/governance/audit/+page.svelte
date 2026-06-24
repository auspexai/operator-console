<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';

  type AuditEntry = {
    id: number;
    occurred_at: string;
    actor_class: string;
    actor_identifier: string | null;
    actor_tenant_id: string | null;
    action: string;
    resource_type: string | null;
    resource_id: string | null;
    payload: Record<string, any> | null;
  };

  type AuditResponse = {
    entries: AuditEntry[];
    total: number;
  };

  const actionOptions = [
    { value: '', label: 'All actions' },
    { value: 'worker.enroll', label: 'worker.enroll' },
    { value: 'worker.quarantine', label: 'worker.quarantine' },
    { value: 'worker.unquarantine', label: 'worker.unquarantine' },
    { value: 'experiment.approve', label: 'experiment.approve' },
    { value: 'experiment.pause', label: 'experiment.pause' },
    { value: 'experiment.resume', label: 'experiment.resume' },
    { value: 'experiment.abort', label: 'experiment.abort' },
    { value: 'account.promote', label: 'account.promote' },
    { value: 'account.demote', label: 'account.demote' },
    { value: 'account.suspend', label: 'account.suspend' },
    { value: 'receipt.issued', label: 'receipt.issued' },
  ];

  const actorClassOptions = [
    { value: '', label: 'All actors' },
    { value: 'maintainer', label: 'maintainer' },
    { value: 'researcher', label: 'researcher' },
    { value: 'worker', label: 'worker' },
    { value: 'system', label: 'system' },
    { value: 'anonymous', label: 'anonymous' },
  ];

  const sinceOptions = [
    { value: '1h', label: 'Last hour' },
    { value: '24h', label: 'Last 24h' },
    { value: '7d', label: 'Last 7d' },
    { value: '', label: 'All' },
  ];

  let entries = $state<AuditEntry[]>([]);
  let total = $state(0);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let filterAction = $state('');
  let filterActorClass = $state('');
  let filterSince = $state('24h');

  function relativeTime(iso: string): string {
    const now = Date.now();
    const then = new Date(iso).getTime();
    const delta = Math.floor((now - then) / 1000);
    if (delta < 0) return 'just now';
    if (delta < 60) return `${delta}s ago`;
    if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
    if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
    return `${Math.floor(delta / 86400)}d ago`;
  }

  function truncateDetails(details: Record<string, any> | null): string {
    if (!details) return '';
    const s = JSON.stringify(details);
    if (s.length <= 80) return s;
    return s.slice(0, 77) + '...';
  }

  async function loadAudit() {
    loading = true;
    error = null;
    try {
      const params = new URLSearchParams();
      if (filterAction) params.set('action', filterAction);
      if (filterActorClass) params.set('actor_class', filterActorClass);
      if (filterSince) {
        const now = Date.now();
        const ms: Record<string, number> = { '1h': 3600e3, '24h': 86400e3, '7d': 604800e3 };
        if (ms[filterSince]) {
          params.set('since', new Date(now - ms[filterSince]).toISOString());
        }
      }
      const qs = params.toString();
      const url = '/api/v0/proxy/audit' + (qs ? `?${qs}` : '');
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body: AuditResponse = await r.json();
      // Standing rule: newest first (most recent audit event at the top).
      entries = (body.entries || []).sort((a, b) =>
        (b.occurred_at ?? '').localeCompare(a.occurred_at ?? ''),
      );
      total = body.total ?? entries.length;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  onMount(loadAudit);
</script>

<svelte:head>
  <title>Audit log — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> audit log</h1>
  </header>
  <Nav />

  <div class="filter-row">
    <select bind:value={filterAction} onchange={loadAudit}>
      {#each actionOptions as opt}
        <option value={opt.value}>{opt.label}</option>
      {/each}
    </select>

    <select bind:value={filterActorClass} onchange={loadAudit}>
      {#each actorClassOptions as opt}
        <option value={opt.value}>{opt.label}</option>
      {/each}
    </select>

    <select bind:value={filterSince} onchange={loadAudit}>
      {#each sinceOptions as opt}
        <option value={opt.value}>{opt.label}</option>
      {/each}
    </select>

    <button onclick={loadAudit}>refresh</button>
  </div>

  {#if loading}
    <p class="muted">Loading audit log...</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else if entries.length === 0}
    <p class="muted">No audit entries matching filters.</p>
  {:else}
    <table>
      <thead>
        <tr>
          <th>time</th>
          <th>actor</th>
          <th>action</th>
          <th>resource</th>
          <th>details</th>
        </tr>
      </thead>
      <tbody>
        {#each entries as entry, i}
          <tr class:alt={i % 2 === 1}>
            <td class="mono" title={entry.occurred_at}>{relativeTime(entry.occurred_at)}</td>
            <td>
              <span class="actor-class badge {entry.actor_class}">{entry.actor_class}</span>
              {#if entry.actor_identifier}<span class="mono">{entry.actor_identifier.slice(0, 12)}…</span>{/if}
            </td>
            <td><span class="action-label">{entry.action}</span></td>
            <td class="mono">{entry.resource_type ?? ''}{entry.resource_id ? ` ${entry.resource_id}` : ''}</td>
            <td class="mono details" title={entry.payload ? JSON.stringify(entry.payload) : ''}>{truncateDetails(entry.payload)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p class="muted">{total} entry/entries total{total !== entries.length ? ` (showing ${entries.length})` : ''}</p>
  {/if}
</main>

<style>
  main { max-width: 1100px; margin: 0 auto; padding: 2em 1.25em; }
  header { border-bottom: 1px solid #2a2e3a; padding-bottom: 0.75em; margin-bottom: 1.5em; }
  h1 { margin: 0; font-size: 1.5em; font-weight: 600; color: #fff; }
  .brand { color: #a78bfa; }
  .brand-link { text-decoration: none; color: inherit; }
  .filter-row { display: flex; gap: 0.5em; margin-bottom: 1.25em; flex-wrap: wrap; align-items: center; }
  .filter-row select { padding: 0.4em 0.6em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; font-size: 0.9em; }
  .filter-row select:focus { outline: none; border-color: #a78bfa; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
  th { text-align: left; padding: 0.5em; border-bottom: 2px solid #2a2e3a; color: #9ca3af; font-weight: 500; background: #16192a; }
  td { padding: 0.5em; border-bottom: 1px solid #1a1e2a; }
  tr.alt { background: #0f1225; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .details { max-width: 18em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #6b7280; }
  .action-label { color: #a78bfa; font-weight: 500; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.maintainer { background: #4c1d95; color: #c4b5fd; }
  .badge.researcher { background: #1e3a5f; color: #93c5fd; }
  .badge.worker { background: #14532d; color: #86efac; }
  .badge.system { background: #854d0e; color: #fde68a; }
  .badge.anonymous { background: #374151; color: #6b7280; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.4em 0.85em; border-radius: 4px; cursor: pointer; font: inherit; font-size: 0.85em; }
  button:hover { background: #2a2e3a; }
</style>
