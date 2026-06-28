<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';

  // Triage-first IA (ui_triage_first_ia_redesign.md §4.1): NOW is the
  // attention queue; Run = the live operational records; Records = the
  // browse/audit surfaces. /scheduler dissolved in I2 (its sections moved to
  // NOW + /workers + /models + the experiment record); only a redirect remains.
  // /tenants dissolved 2026-06-12 (one home per fact: account = the root) —
  // tenants nest under the Accounts pages.
  type NavLink = { href: string; label: string; external?: boolean };
  // The coordinator's API docs (Swagger/ReDoc) are maintainer-gated, so they load
  // through the console's own authed origin (/maintainer/*), which proxies the
  // coordinator schema with the service token — the session cookie does the
  // browser-side auth. Not on the public coordinator landing page.
  const groups: { label: string | null; links: NavLink[] }[] = [
    { label: null, links: [{ href: '/', label: 'Now' }] },
    {
      label: 'Run',
      links: [
        { href: '/workers', label: 'Workers' },
        { href: '/models', label: 'Models' },
      ],
    },
    {
      label: 'Records',
      links: [
        { href: '/accounts', label: 'Accounts' },
        // Receipt verification lives on the public, canonical verifier
        // (verify.html — certs catalog + Rekor + authorized-signer roster),
        // so the console links out rather than duplicating it.
        { href: 'https://auspexai.network/verify.html', label: 'Verify', external: true },
      ],
    },
    {
      label: 'Governance',
      links: [
        { href: '/governance/config', label: 'Config' },
        { href: '/governance/audit', label: 'Audit' },
      ],
    },
    {
      label: 'API',
      links: [
        { href: '/maintainer/docs', label: 'Swagger', external: true },
        { href: '/maintainer/redoc', label: 'ReDoc', external: true },
      ],
    },
  ];

  // E14: maintainer "needs attention" — approved experiments stuck with zero work
  // units (driver crashed / abandoned / Ctrl-C). A red count badge on Accounts
  // (where experiments live, 3 levels deep + collapsed) so abandoned runs don't
  // sit invisibly; the nav is on every page, so it alerts even from Now, and the
  // link navigates to the triage surface. Color-discipline: red = a real problem.
  let attentionCount = $state(0);

  async function refreshAttention() {
    try {
      const r = await fetch('/api/v0/proxy/maintainer/experiments/attention');
      if (r.ok) attentionCount = (await r.json()).count ?? 0;
    } catch {
      /* transient — keep the last known count */
    }
  }

  onMount(() => {
    refreshAttention();
    const id = setInterval(refreshAttention, 30000);
    return () => clearInterval(id);
  });
</script>

<nav>
  {#each groups as group, i}
    {#if i > 0}<span class="sep" aria-hidden="true"></span>{/if}
    {#if group.label}<span class="group-label">{group.label}</span>{/if}
    {#each group.links as link}
      {#if link.external}
        <a href={link.href} target="_blank" rel="noopener">{link.label} ↗</a>
      {:else}
        <a href={link.href} class:active={link.href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(link.href)}>{link.label}{#if link.href === '/accounts' && attentionCount > 0}<span class="badge" title="{attentionCount} experiment(s) need attention (approved but inert)">{attentionCount}</span>{/if}</a>
      {/if}
    {/each}
  {/each}
</nav>

<style>
  nav { display: flex; gap: 0.5em; margin-bottom: 1.5em; align-items: center; flex-wrap: wrap; }
  a { display: inline-block; padding: 0.4em 0.9em; background: #1f2937; border: 1px solid #2a2e3a; border-radius: 4px; color: #9ca3af; text-decoration: none; font-size: 0.9em; }
  a:hover { background: #2a2e3a; color: #d4d4dc; }
  a.active { background: #2a2e3a; border-color: #a78bfa; color: #fff; }
  .sep { width: 1px; height: 1.4em; background: #2a2e3a; margin: 0 0.35em; }
  .group-label { color: #6b7280; font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.08em; }
  .badge { display: inline-block; margin-left: 0.45em; padding: 0 0.4em; min-width: 1.25em; text-align: center; background: #7f1d1d; color: #fca5a5; border-radius: 999px; font-size: 0.78em; font-weight: 600; vertical-align: baseline; }
</style>
