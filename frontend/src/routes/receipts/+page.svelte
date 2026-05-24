<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';

  let receiptId = $state('');
  let receipt = $state<any>(null);
  let verifyBlob = $state('');
  let verifyResult = $state<any>(null);
  let error = $state<string | null>(null);
  let loading = $state(false);

  async function lookupReceipt() {
    if (!receiptId.trim()) return;
    loading = true;
    error = null;
    receipt = null;
    try {
      const r = await fetch(`/api/v0/proxy/receipts/${encodeURIComponent(receiptId.trim())}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      receipt = await r.json();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  async function verifyReceipt() {
    if (!verifyBlob.trim()) return;
    loading = true;
    error = null;
    verifyResult = null;
    try {
      const r = await fetch('/api/v0/proxy/receipts/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cose_signed_blob_b64: verifyBlob.trim() }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      verifyResult = await r.json();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>Receipts — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> receipts</h1>
  </header>
  <Nav />

  <section>
    <h2>Lookup by receipt ID</h2>
    <div class="input-row">
      <input type="text" bind:value={receiptId} placeholder="rcpt-..." />
      <button onclick={lookupReceipt}>lookup</button>
    </div>
  </section>

  {#if receipt}
    <section>
      <h2>Receipt detail</h2>
      <dl>
        <dt>receipt_id</dt><dd class="mono">{receipt.receipt_id}</dd>
        <dt>experiment</dt><dd class="mono">{receipt.experiment_id}</dd>
        <dt>worker</dt><dd class="mono">{receipt.worker_id}</dd>
        <dt>issued_at</dt><dd class="mono">{receipt.issued_at}</dd>
        <dt>signing_key</dt><dd class="mono">{receipt.signing_key_pubkey_hex}</dd>
      </dl>
      {#if receipt.receipt}
        <h3>Receipt body</h3>
        <pre class="json">{JSON.stringify(receipt.receipt, null, 2)}</pre>
      {/if}
    </section>
  {/if}

  <section>
    <h2>Verify receipt (paste COSE blob base64)</h2>
    <textarea bind:value={verifyBlob} rows="4" placeholder="base64-encoded COSE_Sign1 blob…"></textarea>
    <button onclick={verifyReceipt}>verify</button>
  </section>

  {#if verifyResult}
    <section>
      <h2>Verification result</h2>
      <dl>
        <dt>signature valid</dt>
        <dd>
          {#if verifyResult.signature_valid}
            <span class="badge ok">yes</span>
          {:else}
            <span class="badge errorbadge">no</span>
          {/if}
        </dd>
        <dt>schema valid</dt>
        <dd>
          {#if verifyResult.schema_valid}
            <span class="badge ok">yes</span>
          {:else}
            <span class="badge errorbadge">no</span>
          {/if}
        </dd>
        <dt>signer kid</dt><dd class="mono">{verifyResult.signer_kid ?? '—'}</dd>
        <dt>coordinator mode</dt><dd>{verifyResult.coordinator_mode ?? '—'}</dd>
      </dl>
      {#if verifyResult.errors?.length}
        <h3>Errors</h3>
        <ul class="error-list">
          {#each verifyResult.errors as err}
            <li class="errortext">{err}</li>
          {/each}
        </ul>
      {/if}
      {#if verifyResult.receipt}
        <h3>Decoded receipt</h3>
        <pre class="json">{JSON.stringify(verifyResult.receipt, null, 2)}</pre>
      {/if}
    </section>
  {/if}

  {#if error}
    <p class="errortext">{error}</p>
  {/if}
  {#if loading}
    <p class="muted">Loading…</p>
  {/if}
</main>

<style>
  main { max-width: 1100px; margin: 0 auto; padding: 2em 1.25em; }
  header { border-bottom: 1px solid #2a2e3a; padding-bottom: 0.75em; margin-bottom: 1.5em; }
  h1 { margin: 0; font-size: 1.5em; font-weight: 600; color: #fff; }
  h2 { font-size: 1.05em; font-weight: 600; margin: 1.5em 0 0.5em; color: #fff; }
  h3 { font-size: 0.95em; font-weight: 600; margin: 1em 0 0.3em; color: #d4d4dc; }
  .brand { color: #a78bfa; }
  .brand-link { text-decoration: none; color: inherit; }
  dl { display: grid; grid-template-columns: 12em 1fr; gap: 0.3em 1em; }
  dt { color: #9ca3af; }
  dd { margin: 0; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; word-break: break-all; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.ok { background: #14532d; color: #86efac; }
  .errorbadge { background: #7f1d1d; color: #fca5a5; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  .error-list { padding-left: 1.2em; }
  .input-row { display: flex; gap: 0.5em; margin: 0.5em 0; }
  input, textarea { flex: 1; padding: 0.5em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; font-family: ui-monospace, monospace; font-size: 0.9em; }
  textarea { width: 100%; resize: vertical; }
  pre.json { background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 6px; padding: 1em; overflow-x: auto; font-size: 0.8em; color: #d4d4dc; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.4em 0.85em; border-radius: 4px; cursor: pointer; font: inherit; }
  button:hover { background: #2a2e3a; }
</style>
