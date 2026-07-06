<script lang="ts">
  import { onMount } from 'svelte';
  import LaneStrip from '$lib/components/LaneStrip.svelte';
  import Nav from '$lib/components/Nav.svelte';
  import LiveDot from '$lib/components/LiveDot.svelte';
  import ActivityHeart from '$lib/components/ActivityHeart.svelte';
  import { autoRefresh } from '$lib/live';

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

  // ---- NOW triage data (ui_triage_first_ia_redesign.md §4.2) ----------------
  // One loader feeds every section; poll is the truth, the SSE doorbell nudges.

  type Experiment = {
    experiment_id: string;
    tenant_id: string;
    status: string;
    integrity_policy: string;
    // C14: the (target, floor) replication override. The coordinator derives the
    // integrity_policy label from the target; floor is min corroboration.
    replication_target: number | null;
    replication_floor: number | null;
    submitted_at: string;
    tenant_experiment_label?: string;
    run_phase?: string;
  };

  type SchedExp = {
    experiment_id: string;
    tenant_id: string;
    tenant_experiment_label: string;
    pending: number;
    in_progress: number;
    completed: number;
    required_capabilities: Record<string, string[]>;
    capable_worker_count: number;
    eligible_worker_count: number;
    blocked: boolean;
    block_reason: string | null;
    stalled_units?: number;
  };

  type FleetWorker = {
    worker_id: string;
    trust_tier: number;
    last_heartbeat_at: string | null;
    retired_at?: string | null;
    quarantined_at?: string | null;
    quarantine_reason?: string | null;
    paused_at?: string | null;
    pause_reason?: string | null;
    capabilities?: {
      worker_version?: string;
      execute_tenant_code?: string;
      models?: string[];
      served_models?: string[];
      self_paused?: boolean;
      thermal?: { current_temp_c?: number; state?: string };
    } | null;
  };

  type Account = {
    account_id: string;
    display_name?: string | null;
    trust_tier?: number;
    suspended_at?: string | null;
    suspension_reason?: string | null;
  };

  const STALE_MS = 180_000; // mirrors worker_status.STALE_HEARTBEAT_MINUTES (3m)

  // Tenant applications (lite view — full review on /requests)
  type TenantApplicationLite = {
    application_id: string;
    github_login: string;
    requested_tenant_id: string;
    affiliation: string;
    status: string; // pending | approved | declined
  };

  let experiments = $state<Experiment[]>([]);
  let tenantApplications = $state<TenantApplicationLite[]>([]);
  let schedExps = $state<SchedExp[]>([]);
  let fleet = $state<FleetWorker[]>([]);
  let suspendedAccounts = $state<Account[]>([]);
  let triageLoading = $state(true);
  let triageError = $state<string | null>(null);
  let triageLive = $state(false);
  let triageStop: (() => void) | null = null;
  let actionLoading = $state(false);

  async function loadTriage(silent = false): Promise<boolean> {
    if (!silent) triageLoading = true;
    try {
      const [expR, appR, schedR, wkrR, acctR] = await Promise.all([
        fetch('/api/v0/proxy/experiments'),
        fetch('/api/v0/proxy/tenant-applications'),
        fetch('/api/v0/proxy/scheduler/state'),
        fetch('/api/v0/proxy/workers'),
        fetch('/api/v0/proxy/accounts'),
      ]);
      if (!expR.ok) throw new Error(`experiments HTTP ${expR.status}`);
      const expBody = await expR.json();
      experiments = expBody.experiments || expBody || [];
      if (appR.ok) tenantApplications = (await appR.json()).applications || [];
      if (schedR.ok) schedExps = (await schedR.json()).experiments || [];
      if (wkrR.ok) {
        const w = await wkrR.json();
        fleet = w.workers || w || [];
      }
      if (acctR.ok) {
        const a = await acctR.json();
        const accounts: Account[] = a.accounts || a || [];
        suspendedAccounts = accounts.filter((acct) => acct.suspended_at);
      }
      triageError = null;
      return true;
    } catch (e) {
      if (!silent) triageError = (e as Error).message;
      return false;
    } finally {
      if (!silent) triageLoading = false;
    }
  }

  // ---- derived triage sections ----------------------------------------------

  let pendingApprovals = $derived(experiments.filter((e) => e.status === 'submitted'));
  let pendingApplications = $derived(tenantApplications.filter((a) => a.status === 'pending'));
  let blockedExps = $derived(schedExps.filter((e) => e.blocked));
  let stalledExps = $derived(schedExps.filter((e) => !e.blocked && (e.stalled_units ?? 0) > 0));
  let pausedExps = $derived(experiments.filter((e) => e.status === 'paused'));

  type Hold = { worker: FleetWorker; kind: string; detail: string };
  let activeFleet = $derived(fleet.filter((w) => !w.retired_at));
  let holds = $derived(
    activeFleet.flatMap((w): Hold[] => {
      const out: Hold[] = [];
      const caps = w.capabilities || {};
      if (w.quarantined_at)
        out.push({ worker: w, kind: 'quarantined', detail: w.quarantine_reason || '' });
      if (w.paused_at)
        out.push({ worker: w, kind: 'operator-paused', detail: w.pause_reason || '' });
      if (caps.self_paused) out.push({ worker: w, kind: 'self-paused', detail: '' });
      if (caps.thermal?.state === 'critical')
        out.push({
          worker: w,
          kind: 'overheating',
          detail: caps.thermal?.current_temp_c != null ? `${caps.thermal.current_temp_c}°C` : '',
        });
      if (
        !w.quarantined_at &&
        !w.paused_at &&
        (!w.last_heartbeat_at ||
          Date.now() - new Date(w.last_heartbeat_at).getTime() > STALE_MS)
      )
        out.push({ worker: w, kind: 'offline', detail: 'no recent heartbeat' });
      return out;
    }),
  );

  let onlineCount = $derived(
    activeFleet.filter(
      (w) =>
        !w.quarantined_at &&
        !w.paused_at &&
        w.last_heartbeat_at &&
        Date.now() - new Date(w.last_heartbeat_at).getTime() <= STALE_MS,
    ).length,
  );
  // Ops heart (surface_liveness_and_activity_view_design.md): fleet throughput
  // pulse = units completed network-wide (summed across scheduler experiments),
  // plus the vitals the maintainer triages on.
  let fleetCompleted = $derived(schedExps.reduce((s, e) => s + (e.completed ?? 0), 0));
  let reviewCount = $derived(pendingApprovals.length + pendingApplications.length);

  // "Running" = genuinely executing work right now, NOT merely status=approved.
  // There's no distinct running state (D12), and an approved experiment that has
  // drained its units (or never started) lingers in 'approved' — so cross-check
  // the scheduler's in-flight count: in_progress > 0 means a worker is on it now.
  let runningExps = $derived(
    experiments.filter((e) => {
      if (e.status !== 'approved') return false;
      // Trust the platform's phase: 'running' now covers between-rounds
      // (settled + recent activity) — requiring in_progress > 0 zeroed this
      // tile ~93% of wall time for round-based drivers (2026-07-04 campaign).
      if (e.run_phase === 'running') return true;
      const s = schedExps.find((x) => x.experiment_id === e.experiment_id);
      return !!s && s.in_progress > 0;
    }),
  );

  let needsCount = $derived(
    pendingApprovals.length +
      pendingApplications.length +
      blockedExps.length +
      stalledExps.length +
      holds.length +
      pausedExps.length +
      suspendedAccounts.length,
  );

  // ---- Review inline actions (canonical fast path — design §4.2.1) ----------

  let approvalForm = $state<{
    experimentId: string;
    replication_target: string;
    replication_floor: string;
    max_unit_duration_seconds: string;
    max_units: string;
    max_concurrent_assignments: string;
    max_payload_bytes: string;
  } | null>(null);

  function showApprovalForm(exp: Experiment) {
    // C14: default to the experiment's replication when present, else the
    // (target 3, floor 2) baseline.
    approvalForm = {
      experimentId: exp.experiment_id,
      replication_target: String(exp.replication_target ?? 3),
      replication_floor: String(exp.replication_floor ?? 2),
      max_unit_duration_seconds: '1800',
      max_units: '500',
      max_concurrent_assignments: '10',
      max_payload_bytes: '1048576',
    };
  }

  async function submitApproval() {
    if (!approvalForm) return;
    actionLoading = true;
    try {
      const body: Record<string, unknown> = {};
      if (approvalForm.replication_target)
        body.replication_target = parseInt(approvalForm.replication_target);
      if (approvalForm.replication_floor)
        body.replication_floor = parseInt(approvalForm.replication_floor);
      if (approvalForm.max_unit_duration_seconds)
        body.max_unit_duration_seconds = parseInt(approvalForm.max_unit_duration_seconds);
      if (approvalForm.max_units) body.max_units = parseInt(approvalForm.max_units);
      if (approvalForm.max_concurrent_assignments)
        body.max_concurrent_assignments = parseInt(approvalForm.max_concurrent_assignments);
      if (approvalForm.max_payload_bytes)
        body.max_payload_bytes = parseInt(approvalForm.max_payload_bytes);

      const r = await fetch(
        `/api/v0/proxy/experiments/${approvalForm.experimentId}/actions/approve`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      );
      if (!r.ok) {
        const detail = await r.json();
        throw new Error(JSON.stringify(detail));
      }
      approvalForm = null;
      await loadTriage(true);
    } catch (e) {
      alert(`Approval failed: ${(e as Error).message}`);
    } finally {
      actionLoading = false;
    }
  }


  function models(caps: Record<string, string[]>): string {
    return (caps?.models || []).join(', ');
  }

  function shortId(id: string): string {
    return id.length > 20 ? id.slice(0, 17) + '…' : id;
  }

  // ---- auth machinery (unchanged) -------------------------------------------

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
      if (!triageStop) {
        loadTriage().then((ok) => (triageLive = ok));
        triageStop = autoRefresh({
          refresh: () => loadTriage(true),
          setLive: (v) => (triageLive = v),
          types: [
            'experiment.submitted',
            'experiment.status',
            'worker.status',
            'network.status',
            'requirement.submitted',
            'requirement.assessed',
            'requirement.resolved',
            'release.published',
            // Tenant-application doorbells (coordinator side in flight;
            // harmless if never emitted — the poll stays the truth).
            'application.submitted',
            'application.resolved',
          ],
        });
      }
    } else {
      if (healthInterval) {
        clearInterval(healthInterval);
        healthInterval = null;
        health = null;
      }
      if (triageStop) {
        triageStop();
        triageStop = null;
        triageLive = false;
      }
    }
  });

  // UI fix C+D: rehydrate from the coordinator's replay ring (survives
  // navigation) — seeds the heart's trace and feeds the experiment lanes.
  type RecentEv = { experiment_id: string | null; at: string; type: string };
  let recentEvents = $state<RecentEv[]>([]);
  const heartSeed = $derived.by(() => {
    const prog = recentEvents.filter((e) => e.type === 'unit.progress' && e.at);
    let c = 0;
    return prog.map((e) => ({ t: Date.parse(e.at), c: ++c }));
  });
  async function loadRecentEvents() {
    try {
      const r = await fetch('/api/v0/proxy/events/recent?limit=1000');
      if (r.ok) recentEvents = (await r.json()).events ?? [];
    } catch {
      /* ring unavailable → views degrade to live-only, as before */
    }
  }

  onMount(() => {
    void loadRecentEvents();
    refreshAuth();
    return () => {
      if (healthInterval) clearInterval(healthInterval);
      if (triageStop) triageStop();
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
        <span class="signed-in">signed in as <a class="gh" href="https://github.com/{auth.github_login}" target="_blank" rel="noopener noreferrer">{auth.github_login} ↗</a></span>
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
    <!-- Post-auth: the NOW triage home (ui_triage_first_ia_redesign.md §4.2).
         Sections render only when non-empty; the empty triage state is the
         "nothing needs you" success state. -->
    <Nav />

    {#if triageLoading}
      <p class="muted">Loading network state…</p>
    {:else if triageError}
      <p class="errortext">Failed to load: {triageError}</p>
    {:else}
      <ActivityHeart
        pulseTotal={fleetCompleted}
        activeWorkers={onlineCount}
        holds={holds.length}
        runningExperiments={runningExps.length}
        awaitingReview={reviewCount}
        online={health?.coord?.reachable ?? null}
        seed={heartSeed}
      />
      <LaneStrip
        events={recentEvents}
        labels={Object.fromEntries(
          experiments.map((e) => [e.experiment_id, e.tenant_experiment_label ?? e.experiment_id])
        )}
      />

      <div class="needs-header">
        {#if needsCount === 0}
          <h2 class="needs-none">Nothing needs you. <LiveDot live={triageLive} /></h2>
        {:else}
          <h2 class="needs-some">
            Needs you ({needsCount}) <LiveDot live={triageLive} />
          </h2>
        {/if}
      </div>

      {#if pendingApprovals.length > 0 || pendingApplications.length > 0}
        <section>
          <h2 class="section">Review</h2>
          {#if pendingApprovals.length > 0}
            <table>
              <thead>
                <tr><th>experiment</th><th>tenant</th><th>label</th><th>submitted</th><th></th></tr>
              </thead>
              <tbody>
                {#each pendingApprovals as exp (exp.experiment_id)}
                  <tr>
                    <td class="mono"><a href="/experiments/{exp.experiment_id}">{exp.experiment_id}</a></td>
                    <td>{exp.tenant_id}</td>
                    <td>{exp.tenant_experiment_label ?? ''}</td>
                    <td class="mono">{exp.submitted_at}</td>
                    <td><button class="primary" onclick={() => showApprovalForm(exp)} disabled={actionLoading}>approve…</button></td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
          {#if pendingApplications.length > 0}
            <table>
              <thead>
                <tr><th>tenant application</th><th>affiliation</th><th>requested tenant</th><th>status</th><th></th></tr>
              </thead>
              <tbody>
                {#each pendingApplications as app (app.application_id)}
                  <tr>
                    <td>@{app.github_login}</td>
                    <td class="muted">{app.affiliation}</td>
                    <td class="mono">{app.requested_tenant_id}</td>
                    <td><span class="badge">{app.status}</span></td>
                    <td><a href="/accounts#applications">review →</a></td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
        </section>
      {/if}

      {#if blockedExps.length > 0 || stalledExps.length > 0}
        <section>
          <h2 class="section">Capacity</h2>
          <table>
            <thead>
              <tr><th>experiment</th><th>problem</th><th>needs</th><th>capable / eligible</th><th></th></tr>
            </thead>
            <tbody>
              {#each blockedExps as e (e.experiment_id)}
                <tr>
                  <td class="mono"><a href="/experiments/{e.experiment_id}">{shortId(e.experiment_id)}</a></td>
                  <td><span class="badge errorbadge">blocked</span> <span class="muted">{e.block_reason ?? ''}</span></td>
                  <td class="mono">{models(e.required_capabilities)}</td>
                  <td>{e.capable_worker_count} / {e.eligible_worker_count}</td>
                  <td><a href="/workers" class="muted">workers →</a></td>
                </tr>
              {/each}
              {#each stalledExps as e (e.experiment_id)}
                <tr>
                  <td class="mono"><a href="/experiments/{e.experiment_id}">{shortId(e.experiment_id)}</a></td>
                  <td><span class="badge warnbadge">{e.stalled_units} stalled unit{e.stalled_units === 1 ? '' : 's'}</span></td>
                  <td class="mono">{models(e.required_capabilities)}</td>
                  <td>{e.capable_worker_count} / {e.eligible_worker_count}</td>
                  <td><a href="/workers" class="muted">workers →</a></td>
                </tr>
              {/each}
            </tbody>
          </table>
        </section>
      {/if}

      {#if holds.length > 0 || pausedExps.length > 0 || suspendedAccounts.length > 0}
        <section>
          <h2 class="section">Holds</h2>
          <table>
            <tbody>
              {#each holds as h (h.worker.worker_id + h.kind)}
                <tr>
                  <td class="mono"><a href="/workers">{h.worker.worker_id}</a></td>
                  <td>
                    <span class="badge {h.kind === 'quarantined' || h.kind === 'overheating' ? 'errorbadge' : h.kind === 'offline' ? 'warnbadge' : ''}">{h.kind}</span>
                  </td>
                  <td class="muted">{h.detail}</td>
                </tr>
              {/each}
              {#each pausedExps as e (e.experiment_id)}
                <tr>
                  <td class="mono"><a href="/experiments/{e.experiment_id}">{e.experiment_id}</a></td>
                  <td><span class="badge warnbadge">experiment paused</span></td>
                  <td></td>
                </tr>
              {/each}
              {#each suspendedAccounts as a (a.account_id)}
                <tr>
                  <td class="mono"><a href="/accounts/{a.account_id}">{a.account_id}</a></td>
                  <td><span class="badge errorbadge">account suspended</span></td>
                  <td class="muted">{a.suspension_reason ?? ''}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </section>
      {/if}

      <!-- Fleet + Running sections removed: the heart above is the summary (it
           already shows workers · coordinator · holds · experiments running ·
           awaiting review). Worker versions self-resolve via the update prompt
           and live on /workers; unit-in-flight/pending detail lives on /scheduler.
           What's left here is the triage that actually needs a human. -->
    {/if}

    <footer>
      <p class="muted">
        {#if health}console <span class="mono">v{health.version}</span> · {/if}IA:
        <code>Documentation/AuspexAI/v0.1.0/ui_triage_first_ia_redesign.md</code> (local).
        Threat model: <code>operator_console_auth_threat_model.md</code> (local).
      </p>
    </footer>
  {/if}
</main>

{#if approvalForm}
  <div class="modal-backdrop">
    <div class="modal">
      <h2>Approve experiment</h2>
      <p class="mono muted">{approvalForm.experimentId}</p>
      <label for="ap-target">Replication target (aspiration)</label>
      <input id="ap-target" type="number" min="1" max="15" bind:value={approvalForm.replication_target} />
      <label for="ap-floor">Replication floor (min corroboration)</label>
      <input id="ap-floor" type="number" min="1" max="15" bind:value={approvalForm.replication_floor} />
      <p class="hint">The coordinator floors both by the tenant's trust tier; target ≥ floor. The integrity label is derived from the target.</p>
      <label for="ap-dur">max unit duration (s)</label>
      <input id="ap-dur" bind:value={approvalForm.max_unit_duration_seconds} />
      <label for="ap-units">max units</label>
      <input id="ap-units" bind:value={approvalForm.max_units} />
      <label for="ap-conc">max concurrent assignments</label>
      <input id="ap-conc" bind:value={approvalForm.max_concurrent_assignments} />
      <label for="ap-bytes">max payload bytes</label>
      <input id="ap-bytes" bind:value={approvalForm.max_payload_bytes} />
      <div class="modal-actions">
        <button class="primary" onclick={submitApproval} disabled={actionLoading}>approve</button>
        <button onclick={() => (approvalForm = null)}>cancel</button>
      </div>
    </div>
  </div>
{/if}


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
  h2.section {
    margin: 1.75em 0 0.25em;
    font-size: 1.1em;
    border-bottom: 1px solid #2a2e3a;
    padding-bottom: 0.3em;
    color: #d4d4dc;
  }
  .needs-header h2 {
    margin: 0.25em 0 0.5em;
    font-size: 1.25em;
  }
  .needs-none {
    color: #9ca3af;
    font-weight: 500;
  }
  .needs-some {
    color: #fcd34d;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.5em 0 1em;
    font-size: 0.92em;
  }
  th {
    text-align: left;
    color: #6b7280;
    font-weight: 500;
    padding: 0.35em 0.6em;
    border-bottom: 1px solid #2a2e3a;
  }
  td {
    padding: 0.4em 0.6em;
    border-bottom: 1px solid #1a1e2a;
    vertical-align: top;
  }
  td a {
    color: #a78bfa;
    text-decoration: none;
  }
  td a:hover {
    text-decoration: underline;
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
  .badge.errorbadge {
    background: #7f1d1d;
    color: #fca5a5;
  }
  .badge.warnbadge {
    background: #713f12;
    color: #fcd34d;
  }
  .auth-pill {
    display: flex;
    gap: 0.6em;
    align-items: center;
  }
  /* GitHub identity as a link (matches the R-D standard: handle + ↗ → github.com). */
  .signed-in {
    color: #9ca3af;
    font-size: 0.9em;
  }
  .gh {
    font-family: ui-monospace, monospace;
    color: #adbac7;
    text-decoration: none;
  }
  .gh:hover {
    text-decoration: underline;
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
  button:disabled {
    opacity: 0.5;
    cursor: default;
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
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10;
  }
  .modal {
    background: #1a1e2a;
    border: 1px solid #2a2e3a;
    border-radius: 8px;
    padding: 1.25em 1.5em;
    width: min(26em, 92vw);
  }
  .modal h2 {
    margin: 0 0 0.5em;
  }
  .modal label {
    display: block;
    font-size: 0.85em;
    color: #9ca3af;
    margin: 0.7em 0 0.25em;
  }
  .modal input {
    width: 100%;
    padding: 0.45em 0.6em;
    font: inherit;
    font-size: 0.95em;
    background: #0a0e1a;
    border: 1px solid #3a3e4a;
    border-radius: 4px;
    color: #d4d4dc;
  }
  .modal-actions {
    display: flex;
    gap: 0.6em;
    margin-top: 1em;
  }
  .modal .hint {
    color: #6b7280;
    font-size: 0.8em;
    margin: 0.5em 0 0;
    line-height: 1.4;
  }
  footer {
    margin-top: 2.5em;
    padding-top: 1em;
    border-top: 1px solid #2a2e3a;
  }
</style>
