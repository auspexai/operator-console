<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';

  type CoordStatus = {
    url: string;
    reachable: boolean | null;
    detail: string | null;
  };

  type Health = {
    status: string;
    version: string;
    server_time: string;
    phase: string;
    coord: CoordStatus;
  };

  type WhoAmI =
    | { signed_in: false }
    | { signed_in: true; github_login: string; github_user_id: number };

  type DeviceFlowStart = {
    user_code: string;
    verification_uri: string;
    device_code: string;
    interval_seconds: number;
    expires_in: number;
  };

  type PollResult =
    | { status: 'pending'; github_error?: string; next_interval_seconds?: number }
    | { status: 'signed_in'; github_login: string; github_user_id: number }
    | { status: 'denied'; reason: string; github_login?: string; setup_token?: string }
    | { status: 'expired' }
    | { status: 'error'; github_error: string };

  type PassphraseMode = 'none' | 'setup' | 'enter' | 'reset';

  let auth = $state<WhoAmI | null>(null);
  let health = $state<Health | null>(null);
  let healthError = $state<string | null>(null);

  let signinError = $state<string | null>(null);
  let deviceFlow = $state<DeviceFlowStart | null>(null);
  let signinStatus = $state<string>('idle');
  let pollHandle: ReturnType<typeof setInterval> | null = null;

  let passphrase = $state('');
  let passphraseConfirm = $state('');
  let passphraseMode = $state<PassphraseMode>('none');
  let setupToken = $state<string | null>(null);
  let setupBusy = $state(false);

  async function refreshAuth() {
    try {
      const r = await fetch('/api/v0/auth/whoami');
      auth = (await r.json()) as WhoAmI;
    } catch (e) {
      auth = { signed_in: false };
    }
  }

  async function refreshHealth() {
    try {
      const r = await fetch('/api/v0/health');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      health = (await r.json()) as Health;
      healthError = null;
    } catch (e) {
      healthError = (e as Error).message;
    }
  }

  async function beginSignin() {
    signinError = null;
    signinStatus = 'requesting code from GitHub…';
    try {
      const r = await fetch('/api/v0/auth/login', { method: 'POST' });
      if (!r.ok) throw new Error(`device code start failed: HTTP ${r.status}`);
      deviceFlow = (await r.json()) as DeviceFlowStart;
      signinStatus = 'waiting for GitHub authorization';
      // Start at GitHub's recommended interval (typically 5s). Floor at 5s
      // since RFC 8628 recommends not going below.
      startPolling(Math.max(deviceFlow.interval_seconds ?? 5, 5));
    } catch (e) {
      signinError = (e as Error).message;
      signinStatus = 'error';
    }
  }

  function startPolling(intervalSeconds: number) {
    stopPolling();
    pollHandle = setInterval(pollOnce, intervalSeconds * 1000);
  }

  async function pollOnce() {
    if (!deviceFlow) return;
    try {
      const pollHeaders: Record<string, string> = {};
      if (passphrase) pollHeaders['X-Operator-Passphrase'] = passphrase;
      const r = await fetch(
        `/api/v0/auth/poll?device_code=${encodeURIComponent(deviceFlow.device_code)}`,
        { headers: pollHeaders },
      );
      if (!r.ok) throw new Error(`poll HTTP ${r.status}`);
      const result = (await r.json()) as PollResult;
      if (result.status === 'signed_in') {
        stopPolling();
        deviceFlow = null;
        signinStatus = 'signed in';
        await refreshAuth();
      } else if (result.status === 'denied') {
        stopPolling();
        deviceFlow = null;
        signinStatus = 'denied';
        if (result.reason === 'passphrase_setup_required' && result.setup_token) {
          setupToken = result.setup_token;
          passphraseMode = 'setup';
          signinError = null;
        } else if (result.reason === 'rage_shell_factor_required' && result.setup_token) {
          setupToken = result.setup_token;
          passphraseMode = 'enter';
          signinError = null;
        } else {
          signinError =
            result.reason === 'not_in_active_maintainers' && result.github_login
              ? `'@${result.github_login}' is not on the active Maintainer roster. Sign-in declined.`
              : `Sign-in declined: ${result.reason}`;
        }
      } else if (result.status === 'expired') {
        stopPolling();
        deviceFlow = null;
        signinStatus = 'expired';
        signinError = 'Device code expired. Click "Sign in" again to restart.';
      } else if (result.status === 'error') {
        stopPolling();
        deviceFlow = null;
        signinStatus = 'error';
        signinError = `GitHub error: ${result.github_error}`;
      } else if (result.status === 'pending' && result.next_interval_seconds) {
        // GitHub asked us to slow down. Restart the interval at the new
        // (longer) cadence. Cap at 30s so a runaway slow_down doesn't
        // make the UI feel completely dead — if GitHub asks for >30s,
        // we still poll at 30s and accept that GitHub may keep saying
        // slow_down (acceptable; the user can click "cancel" + retry).
        const newInterval = Math.min(result.next_interval_seconds, 30);
        signinStatus = `slowed by GitHub rate-limit; now polling every ${newInterval}s`;
        startPolling(newInterval);
      }
      // plain `status === 'pending'` (no next_interval_seconds) → keep polling at current cadence
    } catch (e) {
      stopPolling();
      signinError = (e as Error).message;
      signinStatus = 'error';
    }
  }

  function stopPolling() {
    if (pollHandle) {
      clearInterval(pollHandle);
      pollHandle = null;
    }
  }

  function cancelSignin() {
    stopPolling();
    deviceFlow = null;
    signinStatus = 'idle';
    signinError = null;
    passphraseMode = 'none';
    passphrase = '';
    passphraseConfirm = '';
    setupToken = null;
  }

  async function submitPassphrase() {
    if (!setupToken) return;
    const isSetup = passphraseMode === 'setup' || passphraseMode === 'reset';
    if (isSetup && passphrase !== passphraseConfirm) {
      signinError = 'Passphrases do not match.';
      return;
    }
    if (isSetup && passphrase.length < 8) {
      signinError = 'Passphrase must be at least 8 characters.';
      return;
    }

    signinError = null;
    setupBusy = true;

    if (isSetup) {
      try {
        const r = await fetch('/api/v0/auth/setup-passphrase', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ setup_token: setupToken, passphrase, confirm: passphraseConfirm }),
        });
        const result = await r.json();
        if (r.ok && result.status === 'signed_in') {
          passphraseMode = 'none';
          passphrase = '';
          passphraseConfirm = '';
          setupToken = null;
          signinStatus = 'signed in';
          await refreshAuth();
        } else {
          signinError = result.detail || 'Failed to set passphrase.';
        }
      } catch (e) {
        signinError = (e as Error).message;
      } finally {
        setupBusy = false;
      }
    } else {
      try {
        const r = await fetch('/api/v0/auth/verify-passphrase', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ setup_token: setupToken, passphrase }),
        });
        const result = await r.json();
        if (r.ok && result.status === 'signed_in') {
          passphraseMode = 'none';
          passphrase = '';
          setupToken = null;
          signinStatus = 'signed in';
          await refreshAuth();
        } else {
          signinError = result.detail || 'Incorrect passphrase.';
        }
      } catch (e) {
        signinError = (e as Error).message;
      } finally {
        setupBusy = false;
      }
    }
  }

  async function signOut() {
    await fetch('/api/v0/auth/logout', { method: 'POST' });
    await refreshAuth();
  }

  // Refresh health only when signed in (don't leak coord URL / version to
  // anonymous visitors who might land on the page via CT logs).
  let healthInterval: ReturnType<typeof setInterval> | null = null;

  $effect(() => {
    if (auth?.signed_in) {
      if (!healthInterval) {
        refreshHealth();
        healthInterval = setInterval(refreshHealth, 5000);
      }
    } else {
      if (healthInterval) {
        clearInterval(healthInterval);
        healthInterval = null;
        health = null;
      }
    }
  });

  onMount(() => {
    refreshAuth();
    return () => {
      if (healthInterval) clearInterval(healthInterval);
      stopPolling();
    };
  });
</script>

<svelte:head>
  <title>AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><span class="brand">auspex[ai]</span> operator console</h1>
    <div class="auth-pill">
      {#if !auth}
        <span class="badge">checking auth…</span>
      {:else if auth.signed_in}
        <span class="badge ok">signed in as @{auth.github_login}</span>
        <button onclick={signOut}>sign out</button>
      {:else}
        <span class="badge">not signed in</span>
      {/if}
    </div>
  </header>

  {#if !auth}
    <section>
      <p class="muted">Checking session…</p>
    </section>
  {:else if !auth.signed_in}
    <!-- Anonymous visitors only see the sign-in surface. No coord URL,
         no version info, no roadmap — nothing internal. -->
    <section class="anonymous-landing">
      <h2>Maintainer-only console</h2>
      <p>
        This is the private dashboard for AuspexAI Maintainers. Active Maintainers (per the public
        roster at
        <a
          href="https://github.com/auspexai/.github/blob/main/security/active_maintainers.json"
          target="_blank"
          rel="noopener">auspexai/.github/security/active_maintainers.json</a
        >) can sign in with their GitHub account.
      </p>
      <p class="muted">
        If you're not on the active Maintainer roster, your sign-in will be politely declined; no
        sensitive information is exposed to non-Maintainers.
      </p>

      {#if passphraseMode === 'setup' || passphraseMode === 'reset'}
        <div class="passphrase-prompt">
          <p>
            {passphraseMode === 'setup'
              ? 'GitHub identity verified. Set an operator passphrase for this console.'
              : 'GitHub identity verified. Set a new operator passphrase.'}
          </p>
          <label for="op-passphrase">New passphrase</label>
          <input
            id="op-passphrase"
            type="password"
            autocomplete="new-password"
            placeholder="at least 8 characters"
            bind:value={passphrase}
          />
          <label for="op-passphrase-confirm">Confirm passphrase</label>
          <input
            id="op-passphrase-confirm"
            type="password"
            autocomplete="new-password"
            placeholder="confirm passphrase"
            bind:value={passphraseConfirm}
            onkeydown={(e: KeyboardEvent) => { if (e.key === 'Enter' && passphrase && passphraseConfirm) submitPassphrase(); }}
          />
          <div class="passphrase-actions">
            <button class="primary" onclick={submitPassphrase} disabled={!passphrase || !passphraseConfirm || setupBusy}>
              {setupBusy ? 'Saving…' : passphraseMode === 'setup' ? 'Set passphrase & sign in' : 'Reset passphrase & sign in'}
            </button>
            <button onclick={cancelSignin}>cancel</button>
          </div>
        </div>
      {:else if passphraseMode === 'enter'}
        <div class="passphrase-prompt">
          <p>GitHub identity verified. Enter your operator passphrase.</p>
          <label for="op-passphrase">Operator passphrase</label>
          <input
            id="op-passphrase"
            type="password"
            autocomplete="current-password"
            placeholder="enter passphrase"
            bind:value={passphrase}
            onkeydown={(e: KeyboardEvent) => { if (e.key === 'Enter' && passphrase) submitPassphrase(); }}
          />
          <div class="passphrase-actions">
            <button class="primary" onclick={submitPassphrase} disabled={!passphrase}>
              Sign in
            </button>
            <button onclick={() => { passphraseMode = 'reset'; passphrase = ''; }}>
              forgot passphrase?
            </button>
            <button onclick={cancelSignin}>cancel</button>
          </div>
        </div>
      {:else if !deviceFlow && signinStatus === 'idle'}
        <button class="primary" onclick={beginSignin}>Sign in with GitHub</button>
      {:else if deviceFlow}
        <div class="device-flow">
          <p>1. Open this URL in a new tab:</p>
          <p>
            <a href={deviceFlow.verification_uri} target="_blank" rel="noopener">
              {deviceFlow.verification_uri}
            </a>
          </p>
          <p>2. Enter this code:</p>
          <p class="user-code">{deviceFlow.user_code}</p>
          <p class="muted">3. Authorize the "AuspexAI Worker" OAuth app (Client ID shared with worker).</p>
          <p class="muted">Status: {signinStatus}</p>
          <button onclick={cancelSignin}>cancel</button>
        </div>
      {:else if signinStatus === 'denied' || signinStatus === 'error' || signinStatus === 'expired'}
        <button class="primary" onclick={beginSignin}>Try again</button>
      {/if}

      {#if signinError}
        <p class="errortext">{signinError}</p>
      {/if}
    </section>

    <footer>
      <p class="muted">
        Public AuspexAI surfaces:
        <a href="https://github.com/auspexai" target="_blank" rel="noopener">github.com/auspexai</a> ·
        <a href="https://auspexai.network" target="_blank" rel="noopener">auspexai.network</a>
      </p>
    </footer>
  {:else}
    <!-- Post-auth: full operator content. -->
    <section>
      <h2>Backend health</h2>
      {#if healthError}
        <p class="errortext">Failed to load: {healthError}</p>
      {:else if !health}
        <p class="muted">Loading…</p>
      {:else}
        <dl>
          <dt>operator-console version</dt>
          <dd>{health.version}</dd>
          <dt>phase</dt>
          <dd class="muted">{health.phase}</dd>
          <dt>server time</dt>
          <dd class="mono">{health.server_time}</dd>
          <dt>coord URL</dt>
          <dd class="mono">{health.coord.url}</dd>
          <dt>coord reachable</dt>
          <dd>
            {#if health.coord.reachable === true}
              <span class="badge ok">yes</span>
              <span class="muted">— {health.coord.detail}</span>
            {:else if health.coord.reachable === false}
              <span class="badge errorbadge">no</span>
              <span class="muted">— {health.coord.detail}</span>
            {:else}
              <span class="badge">unknown</span>
            {/if}
          </dd>
        </dl>
      {/if}
    </section>

    <Nav />

    <section>
      <h2>Coming soon</h2>
      <ul class="roadmap">
        <li><strong>O-M4:</strong> Audit log — who did what across the network.</li>
        <li><strong>O-M6:</strong> Experiment detail — per-experiment drill-down with unit history.</li>
        <li><strong>O-M7:</strong> Release pipeline — coordinated worker + coordinator upgrades.</li>
      </ul>
    </section>

    <footer>
      <p class="muted">
        Build plan: <code>Documentation/AuspexAI/v0.1.0/operator_console_design.md §16</code> (local).
        Threat model: <code>operator_console_auth_threat_model.md</code> (local).
      </p>
    </footer>
  {/if}
</main>

<style>
  :global(*) {
    box-sizing: border-box;
  }
  :global(html) {
    font-family: -apple-system, system-ui, 'Segoe UI', Roboto, sans-serif;
    line-height: 1.5;
    color: #d4d4dc;
    background: #0a0e1a;
  }
  :global(body) {
    margin: 0;
  }
  main {
    max-width: 960px;
    margin: 0 auto;
    padding: 2em 1.25em 4em;
  }
  header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1em;
    border-bottom: 1px solid #2a2e3a;
    padding-bottom: 0.75em;
    margin-bottom: 1.5em;
    flex-wrap: wrap;
  }
  h1 {
    margin: 0;
    font-size: 1.5em;
    font-weight: 600;
    color: #ffffff;
  }
  .brand {
    color: #a78bfa;
  }
  h2 {
    font-size: 1.05em;
    font-weight: 600;
    margin: 1.5em 0 0.5em;
    color: #ffffff;
  }
  dl {
    display: grid;
    grid-template-columns: 14em 1fr;
    gap: 0.3em 1em;
    margin: 0;
  }
  dt {
    color: #9ca3af;
  }
  dd {
    margin: 0;
  }
  .badge {
    display: inline-block;
    padding: 0.1em 0.55em;
    border-radius: 3px;
    font-size: 0.85em;
    font-weight: 500;
    background: #2a2e3a;
    color: #9ca3af;
  }
  .badge.ok {
    background: #14532d;
    color: #86efac;
  }
  .badge.errorbadge {
    background: #7f1d1d;
    color: #fca5a5;
  }
  .auth-pill {
    display: flex;
    gap: 0.6em;
    align-items: center;
  }
  button {
    background: #1f2937;
    border: 1px solid #2a2e3a;
    color: #d4d4dc;
    padding: 0.35em 0.85em;
    border-radius: 4px;
    cursor: pointer;
    font: inherit;
  }
  button:hover {
    background: #2a2e3a;
  }
  button.primary {
    background: #a78bfa;
    color: #0a0e1a;
    border-color: #a78bfa;
    font-weight: 600;
  }
  button.primary:hover {
    background: #c4b5fd;
  }
  .muted {
    color: #6b7280;
    font-size: 0.95em;
  }
  .mono {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 0.9em;
  }
  .errortext {
    color: #fca5a5;
  }
  code {
    font-family: ui-monospace, monospace;
    background: #1a1e2a;
    padding: 0.1em 0.35em;
    border-radius: 3px;
    font-size: 0.85em;
  }
  .device-flow {
    background: #1a1e2a;
    border: 1px solid #2a2e3a;
    border-radius: 6px;
    padding: 1em;
    margin: 1em 0;
  }
  .user-code {
    font-family: ui-monospace, monospace;
    font-size: 1.4em;
    letter-spacing: 0.15em;
    background: #0a0e1a;
    padding: 0.5em;
    border-radius: 4px;
    display: inline-block;
    margin: 0.5em 0;
  }
  .passphrase-prompt {
    background: #1a1e2a;
    border: 1px solid #2a2e3a;
    border-radius: 6px;
    padding: 1em;
    margin: 1em 0;
  }
  .passphrase-prompt label {
    display: block;
    font-size: 0.85em;
    color: #9ca3af;
    margin-bottom: 0.3em;
  }
  .passphrase-prompt input {
    width: 100%;
    max-width: 22em;
    padding: 0.5em 0.65em;
    font: inherit;
    font-size: 0.95em;
    background: #0a0e1a;
    border: 1px solid #3a3e4a;
    border-radius: 4px;
    color: #d4d4dc;
  }
  .passphrase-prompt input:focus {
    outline: none;
    border-color: #a78bfa;
  }
  .passphrase-actions {
    display: flex;
    gap: 0.6em;
    margin-top: 0.75em;
  }
  ul.roadmap {
    padding-left: 1.2em;
  }
  ul.roadmap li {
    margin-bottom: 0.5em;
  }
  footer {
    margin-top: 2.5em;
    padding-top: 1em;
    border-top: 1px solid #2a2e3a;
  }
</style>
