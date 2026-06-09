<script lang="ts">
  import { page } from '$app/state';

  // Triage-first IA (ui_triage_first_ia_redesign.md §4.1): NOW is the
  // attention queue; Run = the live operational records; Records = the
  // browse/audit surfaces. /scheduler is transitional — it dissolves in I2.
  const groups = [
    { label: null, links: [{ href: '/', label: 'Now' }] },
    {
      label: 'Run',
      links: [
        { href: '/experiments', label: 'Experiments' },
        { href: '/workers', label: 'Workers' },
        { href: '/scheduler', label: 'Scheduler' },
      ],
    },
    {
      label: 'Records',
      links: [
        { href: '/tenants', label: 'Tenants' },
        { href: '/accounts', label: 'Accounts' },
        { href: '/receipts', label: 'Receipts' },
        { href: '/audit', label: 'Audit' },
      ],
    },
  ];
</script>

<nav>
  {#each groups as group, i}
    {#if i > 0}<span class="sep" aria-hidden="true"></span>{/if}
    {#if group.label}<span class="group-label">{group.label}</span>{/if}
    {#each group.links as link}
      <a href={link.href} class:active={link.href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(link.href)}>{link.label}</a>
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
</style>
