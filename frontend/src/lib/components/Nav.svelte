<script lang="ts">
  import { page } from '$app/state';

  const links = [
    { href: '/', label: 'Overview' },
    { href: '/workers', label: 'Workers' },
    { href: '/accounts', label: 'Accounts' },
    { href: '/tenants', label: 'Tenants' },
    { href: '/scheduler', label: 'Scheduler' },
    { href: '/experiments', label: 'Experiments' },
    { href: '/receipts', label: 'Receipts' },
    { href: '/audit', label: 'Audit' },
  ];
</script>

<nav>
  {#each links as link}
    <a href={link.href} class:active={link.href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(link.href)}>{link.label}</a>
  {/each}
</nav>

<style>
  nav { display: flex; gap: 0.5em; margin-bottom: 1.5em; }
  a { display: inline-block; padding: 0.4em 0.9em; background: #1f2937; border: 1px solid #2a2e3a; border-radius: 4px; color: #9ca3af; text-decoration: none; font-size: 0.9em; }
  a:hover { background: #2a2e3a; color: #d4d4dc; }
  a.active { background: #2a2e3a; border-color: #a78bfa; color: #fff; }
</style>
