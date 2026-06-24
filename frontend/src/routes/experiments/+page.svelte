<script lang="ts">
  import { onMount } from 'svelte';
  import Nav from '$lib/components/Nav.svelte';
  import { autoRefresh } from '$lib/live';
  import LiveDot from '$lib/components/LiveDot.svelte';

  type EnvelopeCheck = { name: string; passed: boolean; detail: string };
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
    // §9 #48 assessment provenance (class-by-tier auto-approval).
    research_class: string | null;
    assessment_decision: string | null; // 'auto' | 'review'
    assessment_tier: number | null;
    assessment_rationale: string | null;
    assessment_envelope: EnvelopeCheck[] | null;
    assessed_by: string | null;
  };

  // Owning-account context: a POINTER (chip → the account hub), NOT a copy. The
  // account-detail page stays the single synthesis surface (one home per fact);
  // the list links up to it + shows the AT-SUBMISSION trust tier (assessment_tier,
  // the value that governed THIS run) — not the account's current tier, which is
  // redundant (the experiment just inherits it). At-submission research-standing
  // isn't snapshotted, so it isn't shown.
  type AcctRef = {
    account_id: string;
    display_name: string | null;
  };

  const envFails = (e: Experiment) =>
    (e.assessment_envelope ?? []).filter((c) => !c.passed).map((c) => c.name);
  const assessmentTitle = (e: Experiment) =>
    [
      e.assessment_rationale,
      e.assessment_tier != null ? `tier T${e.assessment_tier}` : null,
      e.assessed_by ? `by ${e.assessed_by}` : null,
      envFails(e).length ? `failed: ${envFails(e).join(', ')}` : null,
    ]
      .filter(Boolean)
      .join(' · ');

  let experiments = $state<Experiment[]>([]);
  let tenantToAccount = $state<Record<string, AcctRef>>({});
  // §9 #48 review queue = submitted experiments the agent/endpoint routed to a
  // human (decision=review). Lifecycle ACTIONS (approve / pause / abort / resume)
  // live on the experiment record + the Now triage home — this list is browse.
  const reviewQueue = $derived(
    experiments.filter((e) => e.status === 'submitted' && e.assessment_decision === 'review').length,
  );
  let loading = $state(true);
  let error = $state<string | null>(null);
  let live = $state(false);

  async function loadExperiments(silent = false): Promise<boolean> {
    if (!silent) loading = true;
    try {
      const r = await fetch('/api/v0/proxy/experiments');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      // Standing rule: newest first.
      experiments = ((body.experiments || body || []) as Experiment[]).sort((a, b) =>
        (b.submitted_at ?? '').localeCompare(a.submitted_at ?? ''),
      );
      error = null;
      return true;
    } catch (e) {
      if (!silent) error = (e as Error).message;
      return false;
    } finally {
      if (!silent) loading = false;
    }
  }

  // Best-effort: resolve each experiment's tenant → its owning account (+ tier /
  // standing) so a row links UP to the account hub. Mirrors the accounts page's
  // tenant↔account join. On failure, rows fall back to a plain tenant label.
  async function loadAccountLinks(): Promise<void> {
    try {
      const [tenantsRes, acctRes] = await Promise.all([
        fetch('/api/v0/proxy/tenants'),
        fetch('/api/v0/proxy/accounts'),
      ]);
      if (!tenantsRes.ok || !acctRes.ok) return;
      const tenants: { tenant_id: string }[] = (await tenantsRes.json()).tenants || [];
      const accounts: AcctRef[] = (await acctRes.json()).accounts || [];
      const byId: Record<string, AcctRef> = {};
      for (const a of accounts) byId[a.account_id] = a;
      const map: Record<string, AcctRef> = {};
      await Promise.all(
        tenants.map(async (t) => {
          try {
            const lk = await fetch(`/api/v0/proxy/tenants/${encodeURIComponent(t.tenant_id)}/linkage`);
            if (!lk.ok) return;
            const acctId = ((await lk.json()) as { account_id?: string | null }).account_id;
            if (acctId && byId[acctId]) map[t.tenant_id] = byId[acctId];
          } catch {
            /* skip this tenant — best-effort */
          }
        }),
      );
      tenantToAccount = map;
    } catch {
      /* best-effort enrichment — keep whatever rendered last */
    }
  }

  const statusBadge: Record<string, string> = {
    submitted: 'pending-badge',
    approved: 'ok',
    paused: 'paused-badge',
    completed: 'completed-badge',
    aborted: 'aborted-badge',
    archived: 'archived-badge',
  };

  onMount(() => {
    loadExperiments().then((ok) => (live = ok));
    loadAccountLinks();
    // Poll is the truth, the SSE doorbell is a hint (M8 principle).
    return autoRefresh({
      refresh: () => {
        loadAccountLinks();
        return loadExperiments(true);
      },
      setLive: (v) => (live = v),
      types: ['experiment.submitted', 'experiment.status'],
    });
  });
</script>

<svelte:head>
  <title>Experiments — AuspexAI operator console</title>
</svelte:head>

<main>
  <header>
    <h1><a href="/" class="brand-link"><span class="brand">auspex[ai]</span></a> experiments
      {#if !loading}<LiveDot {live} />{/if}
    </h1>
  </header>
  <Nav />

  {#if loading}
    <p class="muted">Loading experiments…</p>
  {:else if error}
    <p class="errortext">Failed to load: {error}</p>
  {:else if experiments.length === 0}
    <p class="muted">No experiments submitted.</p>
  {:else}
    <table>
      <thead>
        <tr>
          <th>experiment_id</th>
          <th>account / tenant</th>
          <th>status</th>
          <th>assessment</th>
          <th>submitted</th>
        </tr>
      </thead>
      <tbody>
        {#each experiments as exp (exp.experiment_id)}
          <tr>
            <td class="mono"><a href="/experiments/{exp.experiment_id}" class="id-link">{exp.experiment_id}</a></td>
            <td>
              {#if tenantToAccount[exp.tenant_id]}
                {@const a = tenantToAccount[exp.tenant_id]}
                <a href="/accounts/{a.account_id}" class="acct-chip" title="Owning account — {a.display_name ?? a.account_id} (click for the account's current standing)">
                  <span class="mono tenant">{exp.tenant_id}</span>
                  {#if exp.assessment_tier != null}
                    <span class="badge tier-{exp.assessment_tier}" title="trust tier at submission — what governed this run">T{exp.assessment_tier}</span>
                  {/if}
                </a>
              {:else}
                <span class="mono">{exp.tenant_id}</span>
              {/if}
            </td>
            <td><span class="badge {statusBadge[exp.status] ?? ''}">{exp.status}</span></td>
            <td title={assessmentTitle(exp)}>
              {#if exp.assessment_decision}
                <span class="badge assess-{exp.assessment_decision}">{exp.assessment_decision}</span>
                {#if exp.research_class}<span class="rclass">{exp.research_class}</span>{/if}
              {:else}
                <span class="muted">—</span>
              {/if}
            </td>
            <td class="mono">{new Date(exp.submitted_at).toLocaleDateString()}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p class="muted">
      {experiments.length} experiment(s)
      {#if reviewQueue > 0}· <span class="review-count">{reviewQueue} pending human review</span>{/if}
      · act on an experiment from its <span class="hint-inline">record</span> (click the id) or the <a href="/" class="id-link">Now</a> queue
    </p>
  {/if}
</main>

<style>
  main { max-width: 1100px; margin: 0 auto; padding: 2em 1.25em; }
  header { border-bottom: 1px solid #2a2e3a; padding-bottom: 0.75em; margin-bottom: 1.5em; }
  h1 { margin: 0; font-size: 1.5em; font-weight: 600; color: #fff; }
  .brand { color: #a78bfa; }
  .brand-link { text-decoration: none; color: inherit; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
  th { text-align: left; padding: 0.5em; border-bottom: 2px solid #2a2e3a; color: #9ca3af; font-weight: 500; }
  td { padding: 0.5em; border-bottom: 1px solid #1a1e2a; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
  .badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 3px; font-size: 0.85em; font-weight: 500; background: #2a2e3a; color: #9ca3af; }
  .badge.ok { background: #14532d; color: #86efac; }
  .pending-badge { background: #854d0e; color: #fde68a; }
  .paused-badge { background: #1e3a5f; color: #93c5fd; }
  .completed-badge { background: #14532d; color: #86efac; }
  .aborted-badge { background: #7f1d1d; color: #fca5a5; }
  .archived-badge { background: #374151; color: #6b7280; }
  /* owning-account chip (pointer to the account hub) */
  .acct-chip { display: inline-flex; align-items: center; gap: 0.35em; text-decoration: none; color: inherit; }
  .acct-chip .tenant { color: #c4b5fd; }
  .acct-chip:hover .tenant { text-decoration: underline; }
  .badge.tier-0 { background: #1f2937; }
  .badge.tier-1 { background: #1e3a5f; color: #93c5fd; }
  .badge.tier-2 { background: #14532d; color: #86efac; }
  .badge.tier-3 { background: #4c1d95; color: #c4b5fd; }
  /* §9 #48 assessment chips */
  .assess-auto { background: #14532d; color: #86efac; }
  .assess-review { background: #854d0e; color: #fde68a; }
  .rclass { font-family: ui-monospace, monospace; font-size: 0.78em; color: #9ca3af; margin-left: 0.35em; }
  .review-count { color: #fde68a; }
  .muted { color: #6b7280; font-size: 0.95em; }
  .hint-inline { color: #a78bfa; }
  .errortext { color: #fca5a5; }
  .id-link { color: #a78bfa; text-decoration: none; }
  .id-link:hover { text-decoration: underline; }
</style>
