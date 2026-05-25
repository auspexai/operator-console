<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';

  let receiptId = $state('');
  let receipt = $state<any>(null);
  let verifyBlob = $state('');
  let verifyResult = $state<any>(null);
  let error = $state<string | null>(null);
  let loading = $state(false);
  let coseExpanded = $state(false);

  function truncateHex(hex: string, len = 16): string {
    if (!hex || hex.length <= len * 2) return hex ?? '';
    return hex.slice(0, len) + '...' + hex.slice(-len);
  }

  async function copyToClipboard(text: string) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {}
  }

  async function lookupReceipt() {
    if (!receiptId.trim()) return;
    loading = true;
    error = null;
    receipt = null;
    coseExpanded = false;
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
    <section class="card">
      <h2>Receipt metadata</h2>
      <dl>
        <dt>receipt_id</dt><dd class="mono">{receipt.receipt_id}</dd>
        <dt>experiment</dt>
        <dd class="mono"><a href="/experiments/{receipt.experiment_id}" class="id-link">{receipt.experiment_id}</a></dd>
        <dt>issued_at</dt><dd class="mono">{receipt.issued_at}</dd>
        <dt>signing_key</dt>
        <dd class="mono">
          <span title={receipt.signing_key_pubkey_hex}>{truncateHex(receipt.signing_key_pubkey_hex)}</span>
          <button class="copy-btn" onclick={() => copyToClipboard(receipt.signing_key_pubkey_hex)} title="Copy full key">copy</button>
        </dd>
      </dl>
    </section>

    {#if receipt.receipt}
      <section class="card">
        <h2>Receipt body</h2>
        <dl>
          <dt>version</dt><dd class="mono">{receipt.receipt.version}</dd>
          <dt>tenant</dt><dd class="mono">{receipt.receipt.tenant_id}</dd>
          <dt>worker pubkey</dt>
          <dd class="mono">
            <span title={receipt.receipt.worker_pubkey}>{truncateHex(receipt.receipt.worker_pubkey)}</span>
            <button class="copy-btn" onclick={() => copyToClipboard(receipt.receipt.worker_pubkey)} title="Copy full key">copy</button>
          </dd>
          <dt>work unit IDs</dt>
          <dd class="mono">
            {#if receipt.receipt.work_unit_ids?.length}
              {#each receipt.receipt.work_unit_ids as wuid}
                <span class="tag">{wuid}</span>
              {/each}
            {:else}
              —
            {/if}
          </dd>
          {#if receipt.receipt.time_window}
            <dt>time window</dt>
            <dd class="mono">{receipt.receipt.time_window.start} — {receipt.receipt.time_window.end}</dd>
          {/if}
          {#if receipt.receipt.quorum_agreement}
            <dt>quorum</dt>
            <dd>
              replication={receipt.receipt.quorum_agreement.replication_factor},
              agreeing={receipt.receipt.quorum_agreement.agreeing_workers},
              method={receipt.receipt.quorum_agreement.method}
            </dd>
          {/if}
        </dl>
      </section>

      {#if receipt.receipt.result_hash_anchors?.length}
        <section class="card">
          <h2>Rekor anchors</h2>
          <table>
            <thead>
              <tr>
                <th>log index</th>
                <th>entry UUID</th>
                <th>result SHA-256</th>
              </tr>
            </thead>
            <tbody>
              {#each receipt.receipt.result_hash_anchors as anchor}
                <tr>
                  <td>
                    <a
                      href="https://search.sigstore.dev/?logIndex={anchor.rekor_log_index}"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="rekor-link"
                    >
                      {anchor.rekor_log_index}
                    </a>
                  </td>
                  <td class="mono">{truncateHex(anchor.rekor_entry_uuid, 12)}</td>
                  <td class="mono">{truncateHex(anchor.result_sha256, 12)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </section>
      {/if}
    {/if}

    {#if receipt.cose_signed_blob_b64}
      <section class="card">
        <button class="toggle-btn" onclick={() => (coseExpanded = !coseExpanded)}>
          {coseExpanded ? '▾' : '▸'} Raw COSE blob
        </button>
        {#if coseExpanded}
          <pre class="json">{receipt.cose_signed_blob_b64}</pre>
        {/if}
      </section>
    {/if}
  {/if}

  <section>
    <h2>Verify receipt (paste COSE blob base64)</h2>
    <textarea bind:value={verifyBlob} rows="4" placeholder="base64-encoded COSE_Sign1 blob…"></textarea>
    <button onclick={verifyReceipt}>verify</button>
  </section>

  {#if verifyResult}
    <section class="card">
      <h2>Verification steps</h2>
      <div class="verify-steps">
        <div class="step">
          <span class="step-icon" class:pass={verifyResult.cose_decoded !== false} class:fail={verifyResult.cose_decoded === false}>
            {verifyResult.cose_decoded === false ? '✗' : '✓'}
          </span>
          <span class="step-label">COSE Decode</span>
        </div>
        <div class="step">
          <span class="step-icon" class:pass={verifyResult.signature_valid} class:fail={verifyResult.signature_valid === false}>
            {verifyResult.signature_valid ? '✓' : '✗'}
          </span>
          <span class="step-label">Signature Verification</span>
          {#if verifyResult.signer_kid}
            <span class="step-detail mono" title={verifyResult.signer_kid}>{truncateHex(verifyResult.signer_kid)}</span>
          {/if}
        </div>
        <div class="step">
          <span class="step-icon" class:pass={verifyResult.schema_valid} class:fail={verifyResult.schema_valid === false}>
            {verifyResult.schema_valid ? '✓' : '✗'}
          </span>
          <span class="step-label">Schema Validation</span>
        </div>
        <div class="step">
          <span class="step-icon pending">?</span>
          <span class="step-label">Authorized Signer</span>
          <span class="step-detail badge amber-badge">pending</span>
        </div>
      </div>

      {#if verifyResult.errors?.length}
        <div class="error-section">
          <h3>Errors</h3>
          <ul class="error-list">
            {#each verifyResult.errors as err}
              <li class="errortext">{err}</li>
            {/each}
          </ul>
        </div>
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
  .card { background: #11152b; border: 1px solid #1e2340; border-radius: 12px; padding: 1em 1.25em; margin: 1em 0; }
  .card h2 { margin-top: 0; }
  dl { display: grid; grid-template-columns: 12em 1fr; gap: 0.3em 1em; }
  dt { color: #9ca3af; }
  dd { margin: 0; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; word-break: break-all; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.ok { background: #14532d; color: #86efac; }
  .errorbadge { background: #7f1d1d; color: #fca5a5; }
  .amber-badge { background: #854d0e; color: #fde68a; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .errortext { color: #fca5a5; }
  .error-list { padding-left: 1.2em; }
  .error-section { margin-top: 1em; padding-top: 0.75em; border-top: 1px solid #1e2340; }
  .input-row { display: flex; gap: 0.5em; margin: 0.5em 0; }
  input, textarea { flex: 1; padding: 0.5em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; font-family: ui-monospace, monospace; font-size: 0.9em; }
  textarea { width: 100%; resize: vertical; }
  pre.json { background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 6px; padding: 1em; overflow-x: auto; font-size: 0.8em; color: #d4d4dc; }
  button { background: #1f2937; border: 1px solid #2a2e3a; color: #d4d4dc; padding: 0.4em 0.85em; border-radius: 4px; cursor: pointer; font: inherit; }
  button:hover { background: #2a2e3a; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
  th { text-align: left; padding: 0.5em; border-bottom: 2px solid #2a2e3a; color: #9ca3af; font-weight: 500; }
  td { padding: 0.5em; border-bottom: 1px solid #1a1e2a; }
  .id-link { color: #a78bfa; text-decoration: none; }
  .id-link:hover { text-decoration: underline; }
  .rekor-link { color: #a78bfa; text-decoration: none; }
  .rekor-link:hover { text-decoration: underline; }
  .copy-btn { display: inline-block; margin-left: 0.5em; padding: 0.1em 0.45em; font-size: 0.75em; background: #1f2937; border: 1px solid #2a2e3a; border-radius: 3px; color: #9ca3af; cursor: pointer; vertical-align: middle; }
  .copy-btn:hover { background: #2a2e3a; color: #d4d4dc; }
  .tag { display: inline-block; padding: 0.1em 0.45em; background: #1f2937; border: 1px solid #2a2e3a; border-radius: 3px; margin: 0.1em 0.2em 0.1em 0; font-size: 0.9em; }
  .toggle-btn { background: none; border: none; color: #9ca3af; cursor: pointer; padding: 0; font: inherit; font-size: 0.95em; }
  .toggle-btn:hover { color: #d4d4dc; background: none; }
  .verify-steps { display: flex; flex-direction: column; gap: 0.6em; margin: 0.75em 0; }
  .step { display: flex; align-items: center; gap: 0.6em; }
  .step-icon { display: inline-flex; align-items: center; justify-content: center; width: 1.5em; height: 1.5em; border-radius: 50%; font-size: 0.85em; font-weight: 700; background: #2a2e3a; color: #9ca3af; }
  .step-icon.pass { background: #14532d; color: #86efac; }
  .step-icon.fail { background: #7f1d1d; color: #fca5a5; }
  .step-icon.pending { background: #854d0e; color: #fde68a; }
  .step-label { font-weight: 500; color: #d4d4dc; }
  .step-detail { color: #9ca3af; font-size: 0.85em; }
</style>
