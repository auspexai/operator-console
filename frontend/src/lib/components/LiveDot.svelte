<script lang="ts">
  // Shared live/stale indicator (M6). Used identically in every data page's
  // header so the meaning is consistent network-wide:
  //   ● live  — this page auto-refreshes and the last refresh SUCCEEDED.
  //   ● stale — the background refresh is currently failing, so what's on
  //             screen may be out of date (e.g. lost connection).
  // It reflects the *poll* (the source of truth), not merely the SSE socket —
  // so it stays honest even on pages that have no live events, only the poll.
  let { live }: { live: boolean } = $props();
</script>

{#if live}
  <span class="dot live" title="live — updates on its own (live events + a background refresh); no manual reload needed">● live</span>
{:else}
  <span class="dot stale" title="stale — auto-refresh is failing right now; the data shown may be out of date">● stale</span>
{/if}

<style>
  .dot { font-size: 0.55em; font-weight: 500; vertical-align: middle; margin-left: 0.5em; }
  .dot.live { color: #86efac; }
  .dot.stale { color: #fbbf24; }
</style>
