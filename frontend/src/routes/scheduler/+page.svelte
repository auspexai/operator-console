<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';

  // I2 (ui_triage_first_ia_redesign.md §4.3): /scheduler dissolved. Its
  // sections moved to their canonical homes — blocked/stalled triage → the NOW
  // home; worker eligibility → /workers; model catalog + new-requirement queue
  // → /models; set-policy + pre-stage → the experiment record. This route stays
  // only as a redirect so any bookmarked /scheduler link lands somewhere useful.
  onMount(() => {
    goto('/', { replaceState: true });
  });
</script>

<svelte:head>
  <title>Scheduler moved — AuspexAI operator console</title>
</svelte:head>

<main>
  <p class="muted">
    The scheduler view was reorganized. Redirecting to the home triage queue…
    <a href="/">go now</a>. Worker eligibility now lives on <a href="/workers">Workers</a>;
    the model catalog + requests on <a href="/models">Models</a>.
  </p>
</main>

<style>
  main { max-width: 720px; margin: 4em auto; padding: 0 1.25em; }
  .muted { color: #9ca3af; }
  a { color: #a78bfa; }
</style>
