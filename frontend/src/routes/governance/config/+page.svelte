<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';

  // Governance · Config — "what runs without your approval." Two coordinator-
  // authoritative auto-approval levers, relocated here from the (dissolving)
  // requests page: (1) certified profiles (RFC 0001 / Ethics §6.7), (2) the
  // frontier tier-gate (assessment_policy). The experiment-assessment ENGINE
  // (rage-local) enforces the gate; its status is shown for context. The
  // software-request drafting agent retired with the move to GitHub, so it is
  // intentionally absent here.

  type Cert = {
    package_sha256: string;
    snapshot_version: string;
    tenant_id: string;
    profile_name: string;
    status: string;
    replication_floor: number;
    advisor: string | null;
    rekor_log_index: number | null;
  };
  type GatePolicy = { enabled: boolean; min_tier: number };
  type ExpAgentStatus = { installed: boolean; timer_active?: boolean };

  let certs = $state<Cert[]>([]);
  // Re-certification staleness (coordinator-detected): a newer build of a
  // certified profile was submitted (same locked fields, different package).
  let stale = $state<Record<string, { newer_package_sha256: string; seen_at: string }>>({});
  let activeCerts = $derived(certs.filter((c) => c.status === 'certified'));
  let gate = $state<GatePolicy | null>(null);
  let expAgent = $state<ExpAgentStatus | null>(null);
  let gateChoice = $state<'off' | 't2' | 't3'>('off');
  let gateSaving = $state(false);
  let loading = $state(true);

  // The gate's persisted value as the dropdown choice.
  let gateSaved = $derived(gate && gate.enabled ? (gate.min_tier === 3 ? 't3' : 't2') : 'off');

  async function loadCerts() {
    try {
      const r = await fetch('/api/v0/proxy/certifications');
      if (r.ok) certs = (await r.json()).certifications ?? [];
    } catch {
      /* certifications panel is best-effort */
    }
  }
  async function loadGate() {
    try {
      const r = await fetch('/api/v0/proxy/assessment-policy');
      if (r.ok) {
        gate = await r.json();
        gateChoice = gateSaved as 'off' | 't2' | 't3';
      }
    } catch {
      /* gate card is best-effort */
    }
  }
  async function loadExpAgent() {
    try {
      const r = await fetch('/api/v0/agent/experiment-assessment');
      if (r.ok) expAgent = await r.json();
    } catch {
      /* engine card is best-effort */
    }
  }

  async function saveGate() {
    const enabled = gateChoice !== 'off';
    const min_tier = gateChoice === 't3' ? 3 : 2;
    gateSaving = true;
    try {
      const r = await fetch('/api/v0/proxy/assessment-policy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, min_tier }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await loadGate();
    } catch (e) {
      alert(`gate update failed: ${(e as Error).message}`);
    } finally {
      gateSaving = false;
    }
  }

  async function revokeCert(c: Cert) {
    const reason = prompt(
      `Revoke certification for ${c.tenant_id}/${c.profile_name} @ ${c.snapshot_version}?\n\n` +
        `Its runs stop auto-clearing and revert to review. Reason (required):`,
    );
    if (!reason || !reason.trim()) return;
    try {
      const r = await fetch(`/api/v0/proxy/certifications/${c.package_sha256}/revoke`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: reason.trim() }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await loadCerts();
    } catch (e) {
      alert(`revoke failed: ${(e as Error).message}`);
    }
  }

  async function loadStaleness() {
    try {
      const r = await fetch('/api/v0/proxy/certifications/staleness');
      if (r.ok) stale = (await r.json()).stale ?? {};
    } catch {
      /* staleness is best-effort */
    }
  }

  onMount(async () => {
    await Promise.all([loadCerts(), loadGate(), loadExpAgent(), loadStaleness()]);
    loading = false;
  });
</script>

<svelte:head>
  <title>Governance · Config — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> governance · config</h1>
  </header>
  <Nav />

  <h2 class="section">Auto-approval — what runs without your approval</h2>
  <p class="muted">
    Two coordinator-authoritative levers — no LLM, no cost. Every experiment is still assessed and
    queued; these only decide what auto-clears.
  </p>

  {#if loading}
    <p class="muted">Loading…</p>
  {:else}
    <!-- Lever 1: certified profiles -->
    <div class="lever">
      <div class="lever-h">
        Certified profiles <span class="muted">— always auto-run (vetted, declawed; RFC 0001 / §6.7)</span>
      </div>
      {#if activeCerts.length === 0}
        <p class="hint">
          None certified. Certify a starter on the coordinator (<code>certification issue</code>) to
          make its runs auto-clear.
        </p>
      {:else}
        <table class="cert-table">
          <tbody>
            {#each activeCerts as c (c.package_sha256)}
              <tr>
                <td class="mono">{c.tenant_id}/{c.profile_name}</td>
                <td class="mono muted">
                  {c.snapshot_version}
                  {#if stale[c.package_sha256]}
                    <span
                      class="stale-chip"
                      title={`A newer build (pkg ${stale[c.package_sha256].newer_package_sha256.slice(0, 12)}…) was submitted ${new Date(stale[c.package_sha256].seen_at).toLocaleString()} and reverted to review by the content-addressed gate. Re-certify it (certification issue --reissue) to let it auto-clear.`}
                    >⚠ newer build — re-certify</span>
                  {/if}
                </td>
                <td class="muted">floor {c.replication_floor}</td>
                <td class="muted">{c.advisor ? `advisor: ${c.advisor}` : 'low-risk'}</td>
                <td class="muted">
                  {#if c.rekor_log_index != null}
                    <a
                      href={`https://auspexai.network/verify.html?cert=${c.package_sha256}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="open the public verifier for this certificate (signature + roster + Rekor inclusion)">verify · rekor {c.rekor_log_index}</a>
                  {:else}
                    <span title="anchor pending — run `certification backfill-rekor`">un-anchored</span>
                  {/if}
                </td>
                <td><button class="linkish" onclick={() => revokeCert(c)}>revoke</button></td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>

    <!-- Lever 2: the frontier tier-gate -->
    <div class="lever">
      <div class="lever-h">
        Trusted tenants' uncertified research
        <span class="muted">— the frontier that produces certifiable profiles</span>
      </div>
      <select class="gate-select" bind:value={gateChoice} onchange={saveGate} disabled={gateSaving}>
        <option value="off">Off — I review every uncertified experiment</option>
        <option value="t2">Auto-approve routine from trusted tenants (T2+)</option>
        <option value="t3">Auto-approve routine from vetted tenants only (T3)</option>
      </select>
      <p class="hint">
        Does not affect certified profiles. The engine still assesses + queues every experiment;
        "off" only withholds the auto-approve.
      </p>
      {#if expAgent && !expAgent.timer_active}
        <div class="warn">Engine stopped — auto-approval won't run until it's started.</div>
      {/if}
    </div>
  {/if}
</main>

<style>
  main { max-width: 1100px; margin: 0 auto; padding: 2em 1.25em; }
  header { border-bottom: 1px solid #2a2e3a; padding-bottom: 0.75em; margin-bottom: 1.5em; }
  h1 { margin: 0; font-size: 1.5em; font-weight: 600; color: #fff; }
  h2.section { margin: 0.5em 0 0.25em; font-size: 1.1em; font-weight: 600; color: #d4d4dc; }
  .brand { color: #a78bfa; }
  .brand-link { text-decoration: none; color: inherit; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .lever { border: 1px solid #1e2638; border-left: 3px solid #a78bfa; border-radius: 6px; background: #10131c; padding: 0.85em 1em; margin: 1em 0; max-width: 64ch; }
  .lever-h { color: #e6e9f0; font-weight: 600; font-size: 0.95em; margin-bottom: 0.5em; }
  .lever-h .muted { font-weight: 400; }
  .hint { color: #8b93a7; font-size: 0.85em; margin: 0.5em 0 0; line-height: 1.4; }
  .hint code { background: #0a0e1a; padding: 0.05em 0.35em; border-radius: 3px; font-size: 0.92em; }
  .warn { color: #fbbf24; font-size: 0.85em; margin-top: 0.5em; }
  .stale-chip { display: inline-block; margin-left: 0.4em; padding: 0.05em 0.5em; border-radius: 999px; font-size: 0.78em; font-weight: 600; background: #78350f; color: #fcd34d; border: 1px solid #b45309; cursor: help; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .cert-table { width: 100%; border-collapse: collapse; font-size: 0.88em; }
  .cert-table td { padding: 0.3em 0.5em; border-bottom: 1px solid #1a1e2a; }
  .cert-table a { color: #7aa2ff; text-decoration: none; }
  .cert-table a:hover { text-decoration: underline; }
  .gate-select { padding: 0.4em 0.6em; background: #0a0e1a; border: 1px solid #2a2e3a; border-radius: 4px; color: #d4d4dc; font: inherit; font-size: 0.9em; min-width: 24em; }
  .gate-select:focus { outline: none; border-color: #a78bfa; }
  .linkish { background: none; border: none; color: #f87171; cursor: pointer; font: inherit; font-size: 0.85em; padding: 0; text-decoration: underline; }
  .linkish:hover { color: #fca5a5; }
</style>
